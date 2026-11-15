"""CrewAI multi-agent instrumentation adapter.

Maps role-based Crew, Agent, and Task lifecycle execution into hierarchical Argus telemetry.
"""

from __future__ import annotations

import uuid
from typing import Any

from argus.core.schemas import AgentFramework, OperationName, SpanKind
from argus.core.tenancy import TenantContext
from argus.sdk.tracer import ArgusTracer, SpanBuilder


class ArgusCrewAIAdapter:
    """Telemetry instrumentation hook for CrewAI role-based execution flows."""

    def __init__(
        self,
        tracer: ArgusTracer,
        ctx: TenantContext,
        session_id: uuid.UUID,
    ) -> None:
        self._tracer = tracer
        self._ctx = ctx
        self._session_id = session_id
        self._active_tasks: dict[str, tuple[Any, SpanBuilder]] = {}

    async def on_task_start(
        self,
        *,
        task_id: str,
        agent_role: str,
        description: str,
        expected_output: str = "",
    ) -> None:
        """Called when a CrewAI agent takes ownership of a task."""
        cm = self._tracer.start_span(
            self._ctx,
            name=f"crewai.task:{agent_role}",
            span_kind=SpanKind.AGENT,
            operation_name=OperationName.INVOKE_AGENT,
            framework=AgentFramework.CREWAI,
            session_id=self._session_id,
            input_payload={
                "agent_role": agent_role,
                "description": description,
                "expected_output": expected_output,
            },
        )
        builder = await cm.__aenter__()
        builder.set_attribute("crewai.agent_role", agent_role)
        self._active_tasks[task_id] = (cm, builder)

    async def on_task_end(
        self,
        *,
        task_id: str,
        output: str,
        tokens_used: int = 0,
        cost_usd: float = 0.0,
    ) -> None:
        """Called when an agent finishes task execution."""
        record = self._active_tasks.pop(task_id, None)
        if record is not None:
            cm, builder = record
            builder.set_output({"output": output})
            builder.record_tokens(completion_tokens=tokens_used, cost_usd=cost_usd)
            await cm.__aexit__(None, None, None)

    async def on_task_error(
        self,
        *,
        task_id: str,
        error: BaseException | str,
    ) -> None:
        """Called when an agent task execution fails."""
        record = self._active_tasks.pop(task_id, None)
        if record is not None:
            cm, builder = record
            builder.record_error(str(error))
            exc_type = type(error) if isinstance(error, BaseException) else RuntimeError
            exc_val = error if isinstance(error, BaseException) else RuntimeError(str(error))
            exc_tb = error.__traceback__ if isinstance(error, BaseException) else None
            await cm.__aexit__(exc_type, exc_val, exc_tb)
