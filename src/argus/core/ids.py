"""Chronological UUIDv7 generation and lexicographical dotted_order tree indexing."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime

import uuid_utils.compat as uuid_compat

# Segment format: 20261114T164500123456Z<36-char-uuid>
# Embedding UTC microsecond timestamps directly into each path segment allows ClickHouse and
# PostgreSQL to fetch an entire recursive agent trace subtree via a single B-Tree/sparse-index
# prefix scan (`WHERE dotted_order LIKE 'root%'`) without recursive SQL CTE joins.
_SEGMENT_RE = re.compile(
    r"^(?P<ts>\d{8}T\d{6}\d{6}Z)(?P<span_id>[0-9a-fA-F]{8}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})$"
)


def new_uuid7() -> uuid.UUID:
    """Generate a time-ordered RFC 9562 UUIDv7 compatible with standard library uuid.UUID."""
    res: uuid.UUID = uuid_compat.uuid7()
    return res


def utc_now() -> datetime:
    """Return timezone-aware UTC datetime."""
    return datetime.now(UTC)


def format_dotted_segment(started_at: datetime, span_id: uuid.UUID) -> str:
    """Format a single chronological segment for a trace hierarchy."""
    # Reject naive datetimes so distributed workers cannot silently mix local timezones
    # and corrupt lexicographical span sorting.
    if started_at.tzinfo is None or started_at.tzinfo.utcoffset(started_at) is None:
        raise ValueError("started_at must be a timezone-aware datetime.")

    if span_id.version != 7:
        raise ValueError(f"span_id must be UUIDv7 (got version {span_id.version}).")

    utc_dt = started_at.astimezone(UTC)
    ts_str = utc_dt.strftime("%Y%m%dT%H%M%S%fZ")
    return f"{ts_str}{str(span_id).lower()}"


def build_dotted_order(
    started_at: datetime,
    span_id: uuid.UUID,
    parent_dotted_order: str | None = None,
) -> str:
    """Construct a full hierarchical dotted_order string from an optional parent path."""
    segment = format_dotted_segment(started_at, span_id)
    if parent_dotted_order is None or parent_dotted_order == "":
        return segment

    # Validate parent path integrity before appending child segment to prevent malformed trees.
    parse_dotted_order(parent_dotted_order)
    return f"{parent_dotted_order}.{segment}"


def parse_dotted_order(dotted_order: str) -> list[tuple[datetime, uuid.UUID]]:
    """Parse and validate a dotted_order path into (utc_datetime, span_uuid) tuples."""
    if not dotted_order:
        raise ValueError("dotted_order cannot be empty.")

    segments = dotted_order.split(".")
    parsed: list[tuple[datetime, uuid.UUID]] = []

    for seg in segments:
        match = _SEGMENT_RE.match(seg)
        if not match:
            raise ValueError(f"Invalid dotted_order segment format: '{seg}'.")
        ts_raw = match.group("ts")
        span_raw = match.group("span_id")
        dt = datetime.strptime(ts_raw, "%Y%m%dT%H%M%S%fZ").replace(tzinfo=UTC)
        uid = uuid.UUID(span_raw)
        if uid.version != 7:
            raise ValueError(f"Segment UUID '{span_raw}' is not UUIDv7.")
        parsed.append((dt, uid))

    return parsed
