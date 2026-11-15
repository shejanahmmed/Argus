"""AutoGPT and autonomous reasoning loop adapter.

Provides lightweight decorators and context hooks to observe continuous
Thought -> Plan -> Act -> Observe execution cycles without framework lock-in.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from argus.core.schemas import AgentFramework, OperationName, SpanKind
from argus.core.tenancy import TenantContext
from argus.sdk.tracer import ArgusTracer, SpanBuilder


class ArgusAutoGPTTracker:
    """Tracker for autonomous ReAct-style reasoning loops."""

    def __init__(
        self,
        tracer: ArgusTracer,
        ctx: TenantContext,
        session_id: uuid.UUID,
    ) -> None:
        self._tracer = tracer
        self._ctx = ctx
        self._session_id = session_id

    @asynccontextmanager
    async def track_cycle(
        self,
        cycle_number: int,
        *,
        thought: str,
        plan: list[str] | None = None,
    ) -> AsyncIterator[SpanBuilder]:
        """Track an individual reasoning cycle (Thought -> Plan -> Act)."""
        async with self._tracer.start_span(
            self._ctx,
            name=f"autogpt.cycle:{cycle_number}",
            span_kind=SpanKind.AGENT,
            operation_name=OperationName.INVOKE_AGENT,
            framework=AgentFramework.AUTOGPT,
            session_id=self._session_id,
            input_payload={"thought": thought, "plan": plan or []},
        ) as builder:
            builder.set_attribute("autogpt.cycle_number", cycle_number)
            try:
                yield builder
            except BaseException as err:
                builder.record_error(str(err))
                raise
