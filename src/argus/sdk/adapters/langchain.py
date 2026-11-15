"""LangChain and LangChain Expression Language (LCEL) callback instrumentation adapter.

Captures composed RunnableSequence, RunnableParallel, tool executions, retriever lookups,
and LLM completions into OpenTelemetry GenAI + OpenInference compliant spans with error resilience.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from argus.core.schemas import AgentFramework, OperationName, SpanKind
from argus.core.tenancy import TenantContext
from argus.sdk.tracer import ArgusTracer, SpanBuilder


class ArgusLangChainCallbackHandler:
    """Enterprise callback handler compatible with LangChain / LCEL execution flows."""

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
        """Called when an LCEL runnable sequence, parallel branch, or chain begins."""
        name = serialized.get("name") or serialized.get("id", ["LangChainRunnable"])[-1]
        cm = self._tracer.start_span(
            self._ctx,
            name=str(name),
            span_kind=SpanKind.CHAIN,
            operation_name=OperationName.STATE_TRANSITION,
            framework=AgentFramework.LANGCHAIN,
            session_id=self._session_id,
            input_payload=inputs,
        )
        builder = await cm.__aenter__()
        if parent_run_id:
            builder.set_attribute("langchain.parent_run_id", str(parent_run_id))
        self._active_spans[str(run_id)] = (cm, builder)

    async def on_chain_end(
        self,
        outputs: dict[str, Any],
        *,
        run_id: uuid.UUID,
        **kwargs: Any,
    ) -> None:
        """Called when an LCEL chain or runnable finishes successfully."""
        record = self._active_spans.pop(str(run_id), None)
        if record is not None:
            cm, builder = record
            builder.set_output(outputs)
            await cm.__aexit__(None, None, None)

    async def on_chain_error(
        self,
        error: BaseException,
        *,
        run_id: uuid.UUID,
        **kwargs: Any,
    ) -> None:
        """Called when an LCEL chain encounters an unhandled exception."""
        record = self._active_spans.pop(str(run_id), None)
        if record is not None:
            cm, builder = record
            builder.record_error(str(error))
            await cm.__aexit__(type(error), error, error.__traceback__)

    async def on_tool_start(
        self,
        serialized: dict[str, Any],
        input_str: str,
        *,
        run_id: uuid.UUID,
        parent_run_id: uuid.UUID | None = None,
        **kwargs: Any,
    ) -> None:
        """Called when an agent tool is invoked."""
        tool_name = serialized.get("name", "Tool")
        cm = self._tracer.start_span(
            self._ctx,
            name=f"tool:{tool_name}",
            span_kind=SpanKind.TOOL,
            operation_name=OperationName.EXECUTE_TOOL,
            framework=AgentFramework.LANGCHAIN,
            session_id=self._session_id,
            input_payload={"input": input_str},
        )
        builder = await cm.__aenter__()
        builder.set_attribute("tool_name", tool_name)
        if parent_run_id:
            builder.set_attribute("langchain.parent_run_id", str(parent_run_id))
        self._active_spans[str(run_id)] = (cm, builder)

    async def on_tool_end(
        self,
        output: str,
        *,
        run_id: uuid.UUID,
        **kwargs: Any,
    ) -> None:
        """Called when an agent tool completes successfully."""
        record = self._active_spans.pop(str(run_id), None)
        if record is not None:
            cm, builder = record
            builder.set_output({"output": output})
            await cm.__aexit__(None, None, None)

    async def on_tool_error(
        self,
        error: BaseException,
        *,
        run_id: uuid.UUID,
        **kwargs: Any,
    ) -> None:
        """Called when an agent tool throws an error."""
        record = self._active_spans.pop(str(run_id), None)
        if record is not None:
            cm, builder = record
            builder.record_error(str(error))
            await cm.__aexit__(type(error), error, error.__traceback__)

    async def on_llm_start(
        self,
        serialized: dict[str, Any],
        prompts: list[str],
        *,
        run_id: uuid.UUID,
        **kwargs: Any,
    ) -> None:
        """Called when a LangChain chat model or LLM begins generation."""
        model_name = kwargs.get("invocation_params", {}).get("model_name", "unknown_model")
        cm = self._tracer.start_span(
            self._ctx,
            name="chat:completion",
            span_kind=SpanKind.LLM,
            operation_name=OperationName.CHAT,
            framework=AgentFramework.LANGCHAIN,
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
        """Called when LLM generation completes successfully."""
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

    async def on_llm_error(
        self,
        error: BaseException,
        *,
        run_id: uuid.UUID,
        **kwargs: Any,
    ) -> None:
        """Called when LLM inference fails."""
        record = self._active_spans.pop(str(run_id), None)
        if record is not None:
            cm, builder = record
            builder.record_error(str(error))
            await cm.__aexit__(type(error), error, error.__traceback__)

    async def on_retriever_start(
        self,
        serialized: dict[str, Any],
        query: str,
        *,
        run_id: uuid.UUID,
        **kwargs: Any,
    ) -> None:
        """Called when vector retriever query begins."""
        retriever_name = serialized.get("name", "VectorRetriever")
        cm = self._tracer.start_span(
            self._ctx,
            name=f"retriever:{retriever_name}",
            span_kind=SpanKind.RETRIEVER,
            operation_name=OperationName.RETRIEVE,
            framework=AgentFramework.LANGCHAIN,
            session_id=self._session_id,
            input_payload={"query": query},
        )
        builder = await cm.__aenter__()
        self._active_spans[str(run_id)] = (cm, builder)

    async def on_retriever_end(
        self,
        documents: Sequence[Any],
        *,
        run_id: uuid.UUID,
        **kwargs: Any,
    ) -> None:
        """Called when document retrieval finishes."""
        record = self._active_spans.pop(str(run_id), None)
        if record is not None:
            cm, builder = record
            builder.set_output({"document_count": len(documents)})
            await cm.__aexit__(None, None, None)

    async def on_retriever_error(
        self,
        error: BaseException,
        *,
        run_id: uuid.UUID,
        **kwargs: Any,
    ) -> None:
        """Called when vector retriever lookup fails."""
        record = self._active_spans.pop(str(run_id), None)
        if record is not None:
            cm, builder = record
            builder.record_error(str(error))
            await cm.__aexit__(type(error), error, error.__traceback__)
