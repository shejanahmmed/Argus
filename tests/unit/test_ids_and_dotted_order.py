"""Unit tests for chronological UUIDv7 generation and dotted_order tree indexing."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from argus.core.ids import (
    build_dotted_order,
    format_dotted_segment,
    new_uuid7,
    parse_dotted_order,
)


def test_new_uuid7_returns_valid_version_7_uuid() -> None:
    uid1 = new_uuid7()
    uid2 = new_uuid7()
    assert isinstance(uid1, uuid.UUID)
    assert uid1.version == 7
    assert uid2.version == 7
    assert uid1 != uid2


def test_format_dotted_segment_rejects_naive_datetime() -> None:
    naive_dt = datetime(2026, 11, 14, 12, 0, 0)
    span_id = new_uuid7()
    with pytest.raises(ValueError, match="timezone-aware"):
        format_dotted_segment(naive_dt, span_id)


def test_format_dotted_segment_rejects_uuid4() -> None:
    aware_dt = datetime(2026, 11, 14, 12, 0, 0, tzinfo=UTC)
    v4_id = uuid.uuid4()
    with pytest.raises(ValueError, match="UUIDv7"):
        format_dotted_segment(aware_dt, v4_id)


def test_build_and_parse_dotted_order_hierarchy() -> None:
    base_time = datetime(2026, 11, 14, 15, 30, 0, 123456, tzinfo=UTC)
    root_id = new_uuid7()
    child_id = new_uuid7()
    grandchild_id = new_uuid7()

    root_order = build_dotted_order(base_time, root_id)
    child_order = build_dotted_order(
        base_time + timedelta(milliseconds=15),
        child_id,
        root_order,
    )
    grandchild_order = build_dotted_order(
        base_time + timedelta(milliseconds=35),
        grandchild_id,
        child_order,
    )

    assert child_order.startswith(f"{root_order}.")
    assert grandchild_order.startswith(f"{child_order}.")
    assert root_order < child_order < grandchild_order

    parsed = parse_dotted_order(grandchild_order)
    assert len(parsed) == 3
    assert parsed[0] == (base_time, root_id)
    assert parsed[1][1] == child_id
    assert parsed[2][1] == grandchild_id


def test_parse_dotted_order_rejects_corrupted_strings() -> None:
    with pytest.raises(ValueError, match="cannot be empty"):
        parse_dotted_order("")

    with pytest.raises(ValueError, match="Invalid dotted_order segment"):
        parse_dotted_order("not-a-valid-segment")
