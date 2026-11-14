"""High-volume AWS CloudWatch Logs container log parser and trace correlator.

Parses structured JSON container log streams, detects container lifecycle events
(OOM kills, timeouts, crash restarts), and links them directly to active agent traces.
"""

from __future__ import annotations

import contextlib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from argus.core.ids import new_uuid7

_UUID_PATTERN = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)


@dataclass(frozen=True)
class CorrelatedContainerLog:
    """Structured container log record linked to an agent trace."""

    log_id: uuid.UUID
    timestamp: datetime
    log_group: str
    log_stream: str
    severity: str
    message: str
    is_container_anomaly: bool
    trace_id: uuid.UUID | None
    span_id: uuid.UUID | None
    raw_payload: dict[str, Any]


class CloudWatchLogIngestor:
    """Ingestor for high-volume containerized worker JSON infrastructure logs."""

    def parse_log_event(
        self,
        event: dict[str, Any],
        *,
        default_log_group: str = "/aws/ecs/ai-workers",
        default_log_stream: str = "worker-0",
    ) -> CorrelatedContainerLog:
        """Parse an AWS CloudWatch Logs event record and correlate to trace context."""
        log_group = str(event.get("logGroup", default_log_group))
        log_stream = str(event.get("logStream", default_log_stream))

        raw_ts = event.get("timestamp") or event.get("@timestamp")
        if isinstance(raw_ts, (int, float)):
            # CloudWatch timestamp is usually millisecond Unix epoch
            ts = datetime.fromtimestamp(
                raw_ts / 1000.0 if raw_ts > 1e11 else raw_ts, tz=UTC
            )
        elif isinstance(raw_ts, str):
            ts = datetime.fromisoformat(raw_ts).astimezone(UTC)
        else:
            ts = datetime.now(UTC)

        message_raw = str(event.get("message") or event.get("@message") or "")
        parsed_json: dict[str, Any] = {}
        try:
            parsed_json = json.loads(message_raw)
        except (ValueError, TypeError):
            parsed_json = {"raw": message_raw}

        # Check for container anomaly signals
        lowered_msg = message_raw.lower()
        is_anomaly = any(
            anomaly in lowered_msg
            for anomaly in (
                "oomkilled",
                "out of memory",
                "sigterm",
                "sigkill",
                "exit code 137",
                "panic",
                "timeout",
            )
        )

        # Correlate trace_id and span_id from structured JSON fields or regex scan
        extracted_trace_id: uuid.UUID | None = None
        extracted_span_id: uuid.UUID | None = None

        if "trace_id" in parsed_json:
            with contextlib.suppress(ValueError):
                extracted_trace_id = uuid.UUID(str(parsed_json["trace_id"]))

        if "span_id" in parsed_json:
            with contextlib.suppress(ValueError):
                extracted_span_id = uuid.UUID(str(parsed_json["span_id"]))

        # Fallback to regex scanning in unformatted strings
        if extracted_trace_id is None:
            matches = _UUID_PATTERN.findall(message_raw)
            if matches:
                with contextlib.suppress(ValueError):
                    extracted_trace_id = uuid.UUID(matches[0])

        severity = str(
            parsed_json.get("level")
            or event.get("severity")
            or ("ERROR" if is_anomaly else "INFO")
        ).upper()

        return CorrelatedContainerLog(
            log_id=new_uuid7(),
            timestamp=ts,
            log_group=log_group,
            log_stream=log_stream,
            severity=severity,
            message=message_raw,
            is_container_anomaly=is_anomaly,
            trace_id=extracted_trace_id,
            span_id=extracted_span_id,
            raw_payload=event,
        )
