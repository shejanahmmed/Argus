"""High-volume AWS CloudWatch Logs container log parser and trace correlator.

Parses structured JSON container log streams, detects container lifecycle events
(OOM kills, timeouts, crash restarts), and links them directly to active agent traces.
"""

from __future__ import annotations

import contextlib
import json
import re
import uuid
from datetime import UTC, datetime
from typing import Any

from argus.core.ids import new_uuid7
from argus.core.schemas import ContainerAnomalyType, CorrelatedContainerLog

__all__ = [
    "CloudWatchLogIngestor",
    "CorrelatedContainerLog",
]

_UUID_PATTERN = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
_TRACEPARENT_PATTERN = re.compile(
    r"00-([0-9a-fA-F]{32})-([0-9a-fA-F]{16})-[0-9a-fA-F]{2}"
)


class CloudWatchLogIngestor:
    """Ingestor for high-volume containerized worker JSON infrastructure logs."""

    @staticmethod
    def _parse_timestamp(raw_ts: Any) -> datetime:
        """Parse Unix epoch millisecond/second or ISO-8601 timestamp string into UTC datetime."""
        if isinstance(raw_ts, (int, float)):
            # CloudWatch timestamp is usually millisecond Unix epoch
            sec = raw_ts / 1000.0 if raw_ts > 1e11 else float(raw_ts)
            return datetime.fromtimestamp(sec, tz=UTC)
        if isinstance(raw_ts, str):
            try:
                # Handle ISO 8601 / RFC 3339 strings (e.g. 2026-11-15T22:00:00Z)
                cleaned = raw_ts.replace("Z", "+00:00")
                return datetime.fromisoformat(cleaned).astimezone(UTC)
            except ValueError:
                pass
        return datetime.now(UTC)

    @staticmethod
    def _detect_anomaly(message: str) -> tuple[bool, ContainerAnomalyType | None]:
        """Classify message contents into categorized container anomaly taxonomy."""
        lowered = message.lower()

        if (
            "exit code 137" in lowered
            or "exit status 137" in lowered
            or "exited with code 137" in lowered
        ):
            return True, ContainerAnomalyType.EXIT_CODE_137
        if "oomkilled" in lowered or "out of memory" in lowered or "cgroup oom" in lowered:
            return True, ContainerAnomalyType.OOM_KILL
        if "sigkill" in lowered or "signal 9" in lowered or "killed process" in lowered:
            return True, ContainerAnomalyType.SIGKILL
        if "sigterm" in lowered or "signal 15" in lowered or "graceful shutdown timeout" in lowered:
            return True, ContainerAnomalyType.SIGTERM
        if (
            "worker timeout" in lowered
            or "timed out after" in lowered
            or "deadline exceeded" in lowered
        ):
            return True, ContainerAnomalyType.WORKER_TIMEOUT
        if "panic:" in lowered or "fatal error:" in lowered or "fatal runtime error" in lowered:
            return True, ContainerAnomalyType.PANIC_CRASH
        if "segmentation fault" in lowered or "segfault" in lowered:
            return True, ContainerAnomalyType.SEGMENTATION_FAULT

        return False, None

    def parse_log_event(
        self,
        event: dict[str, Any],
        *,
        default_log_group: str = "/aws/ecs/ai-workers",
        default_log_stream: str = "worker-0",
    ) -> CorrelatedContainerLog:
        """Parse an AWS CloudWatch Logs event record and correlate to trace and session context."""
        log_group = str(event.get("logGroup", default_log_group))
        log_stream = str(event.get("logStream", default_log_stream))

        raw_ts = event.get("timestamp") or event.get("@timestamp")
        ts = self._parse_timestamp(raw_ts)

        message_raw = str(event.get("message") or event.get("@message") or "")
        parsed_json: dict[str, Any] = {}
        try:
            parsed_json = json.loads(message_raw)
        except (ValueError, TypeError):
            parsed_json = {"raw": message_raw}

        # 1. Anomaly detection
        is_anomaly, anomaly_type = self._detect_anomaly(message_raw)

        # 2. Correlate trace_id, span_id, session_id
        extracted_trace_id: uuid.UUID | None = None
        extracted_span_id: uuid.UUID | None = None
        extracted_session_id: uuid.UUID | None = None

        # Check JSON fields
        for t_key in ("trace_id", "traceId", "trace"):
            if t_key in parsed_json:
                with contextlib.suppress(ValueError):
                    extracted_trace_id = uuid.UUID(str(parsed_json[t_key]))
                    break

        for s_key in ("span_id", "spanId", "span"):
            if s_key in parsed_json:
                with contextlib.suppress(ValueError):
                    extracted_span_id = uuid.UUID(str(parsed_json[s_key]))
                    break

        for sess_key in ("session_id", "sessionId", "session"):
            if sess_key in parsed_json:
                with contextlib.suppress(ValueError):
                    extracted_session_id = uuid.UUID(str(parsed_json[sess_key]))
                    break

        # Check W3C traceparent header in parsed JSON or message string
        traceparent = parsed_json.get("traceparent") or event.get("traceparent")
        if not traceparent:
            tp_match = _TRACEPARENT_PATTERN.search(message_raw)
            if tp_match:
                traceparent = tp_match.group(0)

        if traceparent:
            tp_match = _TRACEPARENT_PATTERN.search(str(traceparent))
            if tp_match:
                hex_trace = tp_match.group(1)
                hex_span = tp_match.group(2)
                if extracted_trace_id is None:
                    with contextlib.suppress(ValueError):
                        extracted_trace_id = uuid.UUID(hex=hex_trace)
                if extracted_span_id is None:
                    with contextlib.suppress(ValueError):
                        # Pad 16-hex span ID to 32-hex for valid UUID representation
                        extracted_span_id = uuid.UUID(hex=hex_span.zfill(32))

        # Fallback to regex scanning in unformatted strings
        if extracted_trace_id is None:
            raw_matches = _UUID_PATTERN.findall(message_raw)
            valid_trace_matches: list[uuid.UUID] = []
            for m in raw_matches:
                with contextlib.suppress(ValueError):
                    parsed_u = uuid.UUID(m)
                    if parsed_u != extracted_session_id:
                        valid_trace_matches.append(parsed_u)

            if valid_trace_matches:
                extracted_trace_id = valid_trace_matches[0]
                if len(valid_trace_matches) > 1 and extracted_span_id is None:
                    extracted_span_id = valid_trace_matches[1]

        severity = str(
            parsed_json.get("level")
            or event.get("severity")
            or event.get("level")
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
            anomaly_type=anomaly_type,
            trace_id=extracted_trace_id,
            span_id=extracted_span_id,
            session_id=extracted_session_id,
            raw_payload=event,
        )

    def parse_batch(
        self,
        events: list[dict[str, Any]],
        *,
        default_log_group: str = "/aws/ecs/ai-workers",
        default_log_stream: str = "worker-0",
    ) -> list[CorrelatedContainerLog]:
        """Parse a collection of CloudWatch log events."""
        return [
            self.parse_log_event(
                e,
                default_log_group=default_log_group,
                default_log_stream=default_log_stream,
            )
            for e in events
        ]
