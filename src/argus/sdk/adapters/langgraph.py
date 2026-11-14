"""LangGraph and LangChain Expression Language (LCEL) callback instrumentation adapter.

Captures graph node transitions, LLM prompts/completions, tool calls, and state changes
directly into OpenTelemetry GenAI + OpenInference compliant spans.
"""

from __future__ import annotations

import uuid
from typing import Any

from argus.core.schemas import AgentFramework, OperationName, SpanKind
from argus.core.tenancy import TenantContext
from argus.sdk.tracer import ArgusTracer, SpanBuilder


class ArgusLangGraphCallbackHandler:
    """Non-invasive callback handler compatible with LangChain / LangGraph execution loops."""

    def __init__(
        self,
        tracer: ArgusTracer,
        ctx: TenantContext,
        session_id: uuid.UUID,
    ) -> None:
        self._tracer = tracer
        self._ctx = ctx
        self._session_id = session_id
        # Map run_id -> active context manager and builder
        self._active_spans: dict[str, tuple[Any, SpanBuilder]] = {}

    async def on_chain_start(
        self,
        serialized: dict[str, Any],
        inputs: dict[str, Any],
        *,
        run_id: uuid.UUID,
        parent_run_id: uuid.UUID | None = None,
        **kwargs: Any,
    ) -> None:
        """Called when a LangGraph node or LCEL chain starts execution."""
        name = serialized.get("name") or serialized.get("id", ["LangGraphNode"])[-1]
        cm = self._tracer.start_span(
            self._ctx,
            name=str(name),
            span_kind=SpanKind.CHAIN,
            operation_name=OperationName.STATE_TRANSITION,
            framework=AgentFramework.LANGGRAPH,
            session_id=self._session_id,
            input_payload=inputs,
        )
        builder = await cm.__aenter__()
        self._active_spans[str(run_id)] = (cm, builder)

    async def on_chain_end(
        self,
        outputs: dict[str, Any],
        *,
        run_id: uuid.UUID,
        **kwargs: Any,
    ) -> None:
        """Called when a LangGraph node or chain completes."""
        record = self._active_spans.pop(str(run_id), None)
        if record is not None:
            cm, builder = record
            builder.set_output(outputs)
            await cm.__aexit__(None, None, None)

    async def on_tool_start(
        self,
        serialized: dict[str, Any],
        input_str: str,
        *,
        run_id: uuid.UUID,
        parent_run_id: uuid.UUID | None = None,
        **kwargs: Any,
    ) -> None:
        """Called when an agent invokes a tool."""
        tool_name = serialized.get("name", "Tool")
        cm = self._tracer.start_span(
            self._ctx,
            name=f"tool:{tool_name}",
            span_kind=SpanKind.TOOL,
            operation_name=OperationName.EXECUTE_TOOL,
            framework=AgentFramework.LANGGRAPH,
            session_id=self._session_id,
            input_payload={"input": input_str},
        )
        builder = await cm.__aenter__()
        self._active_spans[str(run_id)] = (cm, builder)

    async def on_tool_end(
        self,
        output: str,
        *,
        run_id: uuid.UUID,
        **kwargs: Any,
    ) -> None:
        """Called when tool execution finishes."""
        record = self._active_spans.pop(str(run_id), None)
        if record is not None:
            cm, builder = record
            builder.set_output({"output": output})
            await cm.__aexit__(None, None, None)

    async def on_llm_start(
        self,
        serialized: dict[str, Any],
        prompts: list[str],
        *,
        run_id: uuid.UUID,
        **kwargs: Any,
    ) -> None:
        """Called when an LLM inference call starts."""
        model_name = kwargs.get("invocation_params", {}).get("model_name", "unknown_model")
        cm = self._tracer.start_span(
            self._ctx,
            name="chat:completion",
            span_kind=SpanKind.LLM,
            operation_name=OperationName.CHAT,
            framework=AgentFramework.LANGGRAPH,
            session_id=self._session_id,
            model_name=model_name,
            input_payload={"prompts": prompts},
        )
        builder = await cm.__aenter__()
        self._active_spans[str(run_id)] = (cm, builder)

    async def on_llm_end(
        self,
        response: dict[str, Any],
        *,
        run_id: uuid.UUID,
        **kwargs: Any,
    ) -> None:
        """Called when LLM generation completes."""
        record = self._active_spans.pop(str(run_id), None)
        if record is not None:
            cm, builder = record
            usage = response.get("llm_output", {}).get("token_usage", {})
            prompt_tokens = usage.get("prompt_tokens", 0)
            completion_tokens = usage.get("completion_tokens", 0)
            builder.record_tokens(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            )
            builder.set_output(response)
            await cm.__aexit__(None, None, None)
