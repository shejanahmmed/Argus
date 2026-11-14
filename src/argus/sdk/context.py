"""Distributed execution context propagation using Python contextvars.

Maintains ambient trace_id, session_id, parent_span_id, and dotted_order across async
tasks and thread boundaries without invasive framework patching.
"""

from __future__ import annotations

import contextvars
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from argus.core.ids import new_uuid7


@dataclass(frozen=True)
class TraceContextSnapshot:
    """Immutable snapshot of the active trace hierarchy context."""

    session_id: uuid.UUID
    trace_id: uuid.UUID
    current_span_id: uuid.UUID | None
    current_dotted_order: str | None


_active_session_id: contextvars.ContextVar[uuid.UUID | None] = contextvars.ContextVar(
    "argus_session_id", default=None
)
_active_trace_id: contextvars.ContextVar[uuid.UUID | None] = contextvars.ContextVar(
    "argus_trace_id", default=None
)
_active_span_id: contextvars.ContextVar[uuid.UUID | None] = contextvars.ContextVar(
    "argus_span_id", default=None
)
_active_dotted_order: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "argus_dotted_order", default=None
)


def get_current_session_id() -> uuid.UUID | None:
    """Return the active session_id in the current execution context."""
    return _active_session_id.get()


def get_current_trace_id() -> uuid.UUID | None:
    """Return the active trace_id in the current execution context."""
    return _active_trace_id.get()


def get_current_span_id() -> uuid.UUID | None:
    """Return the active span_id in the current execution context."""
    return _active_span_id.get()


def get_current_dotted_order() -> str | None:
    """Return the active dotted_order string in the current execution context."""
    return _active_dotted_order.get()


def get_trace_snapshot() -> TraceContextSnapshot | None:
    """Return an immutable snapshot of the active trace context if one is active."""
    sess = get_current_session_id()
    tr = get_current_trace_id()
    if sess is None or tr is None:
        return None
    return TraceContextSnapshot(
        session_id=sess,
        trace_id=tr,
        current_span_id=get_current_span_id(),
        current_dotted_order=get_current_dotted_order(),
    )


@contextmanager
def scope_session(
    session_id: uuid.UUID,
    trace_id: uuid.UUID | None = None,
) -> Iterator[TraceContextSnapshot]:
    """Scope an entire agent execution session and root trace."""
    resolved_trace_id = trace_id or new_uuid7()
    tok_sess = _active_session_id.set(session_id)
    tok_tr = _active_trace_id.set(resolved_trace_id)
    tok_span = _active_span_id.set(None)
    tok_dot = _active_dotted_order.set(None)

    snapshot = TraceContextSnapshot(
        session_id=session_id,
        trace_id=resolved_trace_id,
        current_span_id=None,
        current_dotted_order=None,
    )
    try:
        yield snapshot
    finally:
        _active_session_id.reset(tok_sess)
        _active_trace_id.reset(tok_tr)
        _active_span_id.reset(tok_span)
        _active_dotted_order.reset(tok_dot)


@contextmanager
def scope_span(
    span_id: uuid.UUID,
    dotted_order: str,
) -> Iterator[None]:
    """Scope a nested span within an active trace session."""
    tok_span = _active_span_id.set(span_id)
    tok_dot = _active_dotted_order.set(dotted_order)
    try:
        yield None
    finally:
        _active_span_id.reset(tok_span)
        _active_dotted_order.reset(tok_dot)
