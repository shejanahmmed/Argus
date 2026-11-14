"""Command & Control (C2) distributed state management and tool override endpoints."""

from __future__ import annotations

import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from argus.api.dependencies import AppContainer, get_container, get_tenant_context
from argus.core.errors import (
    AuthorizationError,
    CheckpointConflictError,
    EntityNotFoundError,
    InvalidStateTransitionError,
)
from argus.core.ids import new_uuid7
from argus.core.schemas import (
    AgentSession,
    C2OverrideCommand,
    CheckpointRecord,
    JsonPatchOp,
    PendingToolCall,
    ToolOverrideSpec,
)
from argus.core.tenancy import Role, TenantContext

router = APIRouter(prefix="/api/v1/c2", tags=["Command & Control"])


class StateTransitionRequest(BaseModel):
    operator_id: str
    reason: str


class ApplyPatchRequest(BaseModel):
    operator_id: str
    expected_parent_checkpoint_id: uuid.UUID
    patches: list[JsonPatchOp] = Field(min_length=1)
    reason: str = "Operator memory mutation"


class SubmitOverrideRequest(BaseModel):
    tool_call_id: str
    decision: Literal["approve", "edit", "mock", "reject"]
    modified_args: dict[str, Any] | None = None
    mock_output: dict[str, Any] | None = None
    rejection_reason: str | None = None
    operator_id: str
    reason: str


@router.post("/{session_id}/pause", response_model=AgentSession)
async def pause_session(
    session_id: uuid.UUID,
    payload: StateTransitionRequest,
    ctx: Annotated[TenantContext, Depends(get_tenant_context)],
    container: Annotated[AppContainer, Depends(get_container)],
) -> AgentSession:
    """Operator intervention: Pause an active agent session."""
    try:
        session = await container.c2_state_manager.pause_session(
            ctx=ctx,
            session_id=session_id,
            reason=payload.reason,
        )
        await container.event_bus.publish(
            ctx,
            channel="c2.state_changed",
            event={
                "session_id": str(session_id),
                "new_status": session.status.value,
                "operator_id": payload.operator_id,
                "reason": payload.reason,
            },
        )
        return session
    except EntityNotFoundError as err:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(err)) from err
    except InvalidStateTransitionError as err:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(err)) from err
    except AuthorizationError as err:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(err)) from err


@router.post("/{session_id}/resume", response_model=AgentSession)
async def resume_session(
    session_id: uuid.UUID,
    payload: StateTransitionRequest,
    ctx: Annotated[TenantContext, Depends(get_tenant_context)],
    container: Annotated[AppContainer, Depends(get_container)],
) -> AgentSession:
    """Operator intervention: Resume a paused agent session."""
    try:
        session = await container.c2_state_manager.resume_session(
            ctx=ctx,
            session_id=session_id,
        )
        await container.event_bus.publish(
            ctx,
            channel="c2.state_changed",
            event={
                "session_id": str(session_id),
                "new_status": session.status.value,
                "operator_id": payload.operator_id,
                "reason": payload.reason,
            },
        )
        return session
    except EntityNotFoundError as err:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(err)) from err
    except InvalidStateTransitionError as err:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(err)) from err
    except AuthorizationError as err:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(err)) from err


@router.post("/{session_id}/terminate", response_model=AgentSession)
async def terminate_session(
    session_id: uuid.UUID,
    payload: StateTransitionRequest,
    ctx: Annotated[TenantContext, Depends(get_tenant_context)],
    container: Annotated[AppContainer, Depends(get_container)],
) -> AgentSession:
    """Operator intervention: Terminate / kill an agent immediately."""
    try:
        session = await container.c2_state_manager.terminate_session(
            ctx=ctx,
            session_id=session_id,
            reason=payload.reason,
        )
        await container.event_bus.publish(
            ctx,
            channel="c2.state_changed",
            event={
                "session_id": str(session_id),
                "new_status": session.status.value,
                "operator_id": payload.operator_id,
                "reason": payload.reason,
            },
        )
        return session
    except EntityNotFoundError as err:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(err)) from err
    except InvalidStateTransitionError as err:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(err)) from err
    except AuthorizationError as err:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(err)) from err


@router.post("/{session_id}/patch", response_model=CheckpointRecord)
async def apply_json_patch_state(
    session_id: uuid.UUID,
    payload: ApplyPatchRequest,
    ctx: Annotated[TenantContext, Depends(get_tenant_context)],
    container: Annotated[AppContainer, Depends(get_container)],
) -> CheckpointRecord:
    """Apply RFC 6902 JSON patch to agent checkpoint with optimistic lock verification."""
    op_role: Literal[Role.OPERATOR, Role.ADMIN] = (
        Role.ADMIN if ctx.role == Role.ADMIN else Role.OPERATOR
    )
    command = C2OverrideCommand(
        command_id=new_uuid7(),
        tenant_id=ctx.tenant_id,
        workspace_id=ctx.workspace_id,
        session_id=session_id,
        expected_checkpoint_id=payload.expected_parent_checkpoint_id,
        operator_id=payload.operator_id,
        operator_role=op_role,
        action="EDIT_MEMORY",
        memory_patch=tuple(payload.patches),
        reason=payload.reason,
    )

    try:
        new_checkpoint = await container.c2_state_manager.apply_memory_patch(
            ctx=ctx,
            command=command,
        )
        await container.audit_ledger.record_intervention(
            ctx=ctx,
            session_id=session_id,
            command=command,
            details={"patch_count": len(payload.patches)},
        )
        await container.event_bus.publish(
            ctx,
            channel="c2.checkpoint_created",
            event={
                "session_id": str(session_id),
                "checkpoint_id": str(new_checkpoint.checkpoint_id),
                "operator_id": payload.operator_id,
            },
        )
        return new_checkpoint
    except CheckpointConflictError as err:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(err)) from err
    except EntityNotFoundError as err:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(err)) from err
    except (ValueError, KeyError, IndexError) as err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid JSON patch operation: {err}",
        ) from err


@router.get("/{session_id}/pending-tools", response_model=list[PendingToolCall])
async def get_pending_tool_calls(
    session_id: uuid.UUID,
    container: Annotated[AppContainer, Depends(get_container)],
) -> list[PendingToolCall]:
    """Retrieve all pending tool calls awaiting human operator decision."""
    return container.pending_tool_calls.get(str(session_id), [])


@router.post("/{session_id}/pending-tools", response_model=PendingToolCall)
async def register_pending_tool_call(
    session_id: uuid.UUID,
    call: PendingToolCall,
    ctx: Annotated[TenantContext, Depends(get_tenant_context)],
    container: Annotated[AppContainer, Depends(get_container)],
) -> PendingToolCall:
    """Register an intercepted tool call requiring human authorization."""
    container.pending_tool_calls.setdefault(str(session_id), []).append(call)
    await container.event_bus.publish(
        ctx,
        channel="c2.intervention_required",
        event={
            "session_id": str(session_id),
            "tool_call_id": call.tool_call_id,
            "tool_name": call.tool_name,
            "request_digest_sha256": call.request_digest_sha256,
        },
    )
    return call


@router.post("/{session_id}/tool-override")
async def submit_tool_override(
    session_id: uuid.UUID,
    payload: SubmitOverrideRequest,
    ctx: Annotated[TenantContext, Depends(get_tenant_context)],
    container: Annotated[AppContainer, Depends(get_container)],
) -> dict[str, Any]:
    """Submit operator decision (approve/edit/mock/reject) with cryptographic digest check."""
    calls = container.pending_tool_calls.get(str(session_id), [])
    matching_call = next((c for c in calls if c.tool_call_id == payload.tool_call_id), None)
    if matching_call is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No pending tool call found with ID '{payload.tool_call_id}'.",
        )

    spec = ToolOverrideSpec(
        decision=payload.decision,
        request_digest_sha256=matching_call.request_digest_sha256,
        modified_args=payload.modified_args,
        mock_output=payload.mock_output,
        rejection_reason=payload.rejection_reason,
    )

    op_role: Literal[Role.OPERATOR, Role.ADMIN] = (
        Role.ADMIN if ctx.role == Role.ADMIN else Role.OPERATOR
    )
    command = C2OverrideCommand(
        command_id=new_uuid7(),
        tenant_id=ctx.tenant_id,
        workspace_id=ctx.workspace_id,
        session_id=session_id,
        expected_checkpoint_id=new_uuid7(),
        operator_id=payload.operator_id,
        operator_role=op_role,
        action="OVERRIDE_TOOL_CALL",
        tool_override=spec,
        reason=payload.reason,
    )

    try:
        res_payload, should_exec, status_msg = container.tool_override_engine.process_override(
            ctx=ctx,
            command=command,
            pending_call=matching_call,
        )

        container.pending_tool_calls[str(session_id)].remove(matching_call)

        await container.audit_ledger.record_intervention(
            ctx=ctx,
            session_id=session_id,
            command=command,
            details={"status_message": status_msg},
        )
        await container.event_bus.publish(
            ctx,
            channel="c2.override_resolved",
            event={
                "session_id": str(session_id),
                "tool_call_id": payload.tool_call_id,
                "decision": payload.decision,
                "status_message": status_msg,
                "should_execute": should_exec,
            },
        )
        return {
            "status": "ok",
            "decision": payload.decision,
            "should_execute": should_exec,
            "effective_payload": res_payload,
            "message": status_msg,
        }
    except (ValueError, AuthorizationError) as err:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(err)) from err
