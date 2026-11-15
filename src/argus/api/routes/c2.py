"""Command & Control (C2) distributed state management and tool override endpoints."""

from __future__ import annotations

import contextlib
import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from argus.api.dependencies import AppContainer, get_container, get_tenant_context
from argus.c2.lease_manager import HeartbeatStatus
from argus.c2.presets import get_all_presets
from argus.core.errors import (
    AuthorizationError,
    CheckpointConflictError,
    EntityNotFoundError,
    InvalidStateTransitionError,
)
from argus.core.ids import new_uuid7, utc_now
from argus.core.schemas import (
    AgentSession,
    AuditLogEntry,
    C2OverrideCommand,
    CheckpointRecord,
    JsonPatchOp,
    PendingToolCall,
    ResolvedToolOverride,
    SessionStatus,
    StatePreset,
    ToolOverrideSpec,
)
from argus.core.tenancy import Role, TenantContext

router = APIRouter(prefix="/api/v1/c2", tags=["Command & Control"])


class StateTransitionRequest(BaseModel):
    operator_id: str
    reason: str


class CreateCheckpointRequest(BaseModel):
    node_name: str = Field(min_length=1, max_length=128)
    step_index: int = Field(default=0, ge=0)
    memory_state: dict[str, Any] = Field(default_factory=dict)
    expected_parent_checkpoint_id: uuid.UUID | None = None
    pending_tool_call: PendingToolCall | None = None


class ApplyPatchRequest(BaseModel):
    operator_id: str
    expected_parent_checkpoint_id: uuid.UUID | None = None
    patches: list[JsonPatchOp] = Field(min_length=1)
    reason: str = "Operator memory mutation"


class ApplyPresetRequest(BaseModel):
    operator_id: str
    expected_parent_checkpoint_id: uuid.UUID | None = None
    reason: str | None = None


class SubmitOverrideRequest(BaseModel):
    tool_call_id: str
    decision: Literal["approve", "edit", "mock", "reject"]
    modified_args: dict[str, Any] | None = None
    mock_output: dict[str, Any] | None = None
    rejection_reason: str | None = None
    operator_id: str
    reason: str = "Operator tool override decision"
    auto_resume: bool = True


class AuditLogResponse(BaseModel):
    session_id: str
    chain_verified: bool
    entries: list[AuditLogEntry]


class HeartbeatRequest(BaseModel):
    worker_id: str = Field(min_length=1, max_length=128)
    ttl_seconds: float = Field(default=300.0, gt=0.0)


class ReapLeasesResponse(BaseModel):
    reaped_session_ids: list[str]
    reaped_count: int


@router.get("/presets", response_model=list[StatePreset])
async def list_state_presets() -> list[StatePreset]:
    """List all registered Command & Control state mutation presets."""
    return get_all_presets()


@router.post("/{session_id}/pause", response_model=AgentSession)
async def pause_session(
    session_id: uuid.UUID,
    payload: StateTransitionRequest,
    ctx: Annotated[TenantContext, Depends(get_tenant_context)],
    container: Annotated[AppContainer, Depends(get_container)],
) -> AgentSession:
    """Operator intervention: Pause an active or loop-tripped agent session."""
    try:
        session = await container.c2_state_manager.pause_session(
            ctx=ctx,
            session_id=session_id,
            reason=payload.reason,
        )
        await container.audit_store.append_event(
            ctx,
            session_id=session_id,
            event_type="C2_PAUSE",
            payload={"operator_id": payload.operator_id, "reason": payload.reason},
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
    """Operator intervention: Resume a paused agent session and reset loop history."""
    try:
        session = await container.c2_state_manager.resume_session(
            ctx=ctx,
            session_id=session_id,
        )
        container.loop_detector.reset_session(str(session_id), tenant_id=ctx.tenant_id)
        await container.audit_store.append_event(
            ctx,
            session_id=session_id,
            event_type="C2_RESUME",
            payload={"operator_id": payload.operator_id, "reason": payload.reason},
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
        await container.audit_store.append_event(
            ctx,
            session_id=session_id,
            event_type="C2_TERMINATE",
            payload={"operator_id": payload.operator_id, "reason": payload.reason},
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


@router.post("/{session_id}/checkpoints", response_model=CheckpointRecord)
async def create_checkpoint(
    session_id: uuid.UUID,
    payload: CreateCheckpointRequest,
    ctx: Annotated[TenantContext, Depends(get_tenant_context)],
    container: Annotated[AppContainer, Depends(get_container)],
) -> CheckpointRecord:
    """Persist a new versioned agent checkpoint with optimistic concurrency verification."""
    try:
        checkpoint = CheckpointRecord(
            checkpoint_id=new_uuid7(),
            parent_checkpoint_id=payload.expected_parent_checkpoint_id,
            tenant_id=ctx.tenant_id,
            workspace_id=ctx.workspace_id,
            session_id=session_id,
            node_name=payload.node_name,
            step_index=payload.step_index,
            memory_state=payload.memory_state,
            pending_tool_call=payload.pending_tool_call,
            created_at=utc_now(),
        )
        saved = await container.control_store.save_checkpoint(
            ctx=ctx,
            checkpoint=checkpoint,
            expected_parent_id=payload.expected_parent_checkpoint_id,
        )
        await container.event_bus.publish(
            ctx,
            channel="c2.checkpoint_created",
            event={
                "session_id": str(session_id),
                "checkpoint_id": str(saved.checkpoint_id),
                "node_name": saved.node_name,
            },
        )
        return saved
    except CheckpointConflictError as err:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(err)) from err
    except EntityNotFoundError as err:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(err)) from err


@router.get("/{session_id}/checkpoints/latest", response_model=CheckpointRecord | None)
async def get_latest_checkpoint(
    session_id: uuid.UUID,
    ctx: Annotated[TenantContext, Depends(get_tenant_context)],
    container: Annotated[AppContainer, Depends(get_container)],
) -> CheckpointRecord | None:
    """Retrieve the latest checkpoint snapshot for an agent session."""
    try:
        return await container.control_store.get_latest_checkpoint(ctx, session_id)
    except EntityNotFoundError as err:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(err)) from err


@router.get("/{session_id}/checkpoints", response_model=list[CheckpointRecord])
async def list_checkpoints_for_session(
    session_id: uuid.UUID,
    ctx: Annotated[TenantContext, Depends(get_tenant_context)],
    container: Annotated[AppContainer, Depends(get_container)],
) -> list[CheckpointRecord]:
    """Retrieve full chronological checkpoint history for an agent session."""
    try:
        return await container.c2_state_manager.list_checkpoints(ctx, session_id)
    except EntityNotFoundError as err:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(err)) from err


@router.post("/{session_id}/patch", response_model=CheckpointRecord)
async def apply_json_patch_state(
    session_id: uuid.UUID,
    payload: ApplyPatchRequest,
    ctx: Annotated[TenantContext, Depends(get_tenant_context)],
    container: Annotated[AppContainer, Depends(get_container)],
) -> CheckpointRecord:
    """Apply RFC 6902 JSON patch to agent checkpoint with optimistic lock verification."""
    try:
        expected_cp_id = payload.expected_parent_checkpoint_id
        if expected_cp_id is None:
            latest_cp = await container.control_store.get_latest_checkpoint(ctx, session_id)
            if latest_cp is None:
                raise EntityNotFoundError("CheckpointRecord", str(session_id))
            expected_cp_id = latest_cp.checkpoint_id

        op_role: Literal[Role.OPERATOR, Role.ADMIN] = (
            Role.ADMIN if ctx.role == Role.ADMIN else Role.OPERATOR
        )
        command = C2OverrideCommand(
            command_id=new_uuid7(),
            tenant_id=ctx.tenant_id,
            workspace_id=ctx.workspace_id,
            session_id=session_id,
            expected_checkpoint_id=expected_cp_id,
            operator_id=payload.operator_id,
            operator_role=op_role,
            action="EDIT_MEMORY",
            memory_patch=tuple(payload.patches),
            reason=payload.reason,
        )

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


@router.post("/{session_id}/apply-preset/{preset_id}", response_model=CheckpointRecord)
async def apply_preset_to_session(
    session_id: uuid.UUID,
    preset_id: str,
    payload: ApplyPresetRequest,
    ctx: Annotated[TenantContext, Depends(get_tenant_context)],
    container: Annotated[AppContainer, Depends(get_container)],
) -> CheckpointRecord:
    """Apply a standardized pre-built state preset to a paused session's latest checkpoint."""
    try:
        new_checkpoint = await container.c2_state_manager.apply_preset(
            ctx=ctx,
            session_id=session_id,
            preset_id=preset_id,
            operator_id=payload.operator_id,
            expected_checkpoint_id=payload.expected_parent_checkpoint_id,
            reason=payload.reason,
        )
        await container.audit_store.append_event(
            ctx,
            session_id=session_id,
            event_type="C2_PRESET_APPLIED",
            payload={
                "operator_id": payload.operator_id,
                "preset_id": preset_id,
                "checkpoint_id": str(new_checkpoint.checkpoint_id),
            },
        )
        await container.event_bus.publish(
            ctx,
            channel="c2.checkpoint_created",
            event={
                "session_id": str(session_id),
                "checkpoint_id": str(new_checkpoint.checkpoint_id),
                "preset_id": preset_id,
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
            detail=f"Invalid preset state mutation: {err}",
        ) from err


@router.get("/{session_id}/pending-tools", response_model=list[PendingToolCall])
async def get_pending_tool_calls(
    session_id: uuid.UUID,
    ctx: Annotated[TenantContext, Depends(get_tenant_context)],
    container: Annotated[AppContainer, Depends(get_container)],
) -> list[PendingToolCall]:
    """Retrieve all pending tool calls awaiting human operator decision for caller's tenant."""
    key = f"{ctx.tenant_id}:{session_id}"
    calls = container.pending_tool_calls.get(key)
    if calls is None:
        calls = container.pending_tool_calls.get(str(session_id), [])
    return calls


@router.post("/{session_id}/pending-tools", response_model=PendingToolCall)
async def register_pending_tool_call(
    session_id: uuid.UUID,
    call: PendingToolCall,
    ctx: Annotated[TenantContext, Depends(get_tenant_context)],
    container: Annotated[AppContainer, Depends(get_container)],
) -> PendingToolCall:
    """Register an intercepted tool call requiring human authorization within tenant boundary."""
    key = f"{ctx.tenant_id}:{session_id}"
    container.pending_tool_calls.setdefault(key, []).append(call)
    await container.event_bus.publish(
        ctx,
        channel="c2.intervention_required",
        event={
            "session_id": str(session_id),
            "tool_call_id": call.tool_call_id,
            "tool_name": call.tool_name,
            "request_digest_sha256": call.request_digest_sha256,
            "security_risk": call.security_risk,
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
    key = f"{ctx.tenant_id}:{session_id}"
    calls = container.pending_tool_calls.get(key)
    if calls is None:
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

        if key in container.pending_tool_calls:
            calls_list = container.pending_tool_calls[key]
            if matching_call in calls_list:
                calls_list.remove(matching_call)
        elif str(session_id) in container.pending_tool_calls:
            calls_legacy = container.pending_tool_calls[str(session_id)]
            if matching_call in calls_legacy:
                calls_legacy.remove(matching_call)

        # Store resolved override record for agent worker / MCP client retrieval
        resolved = ResolvedToolOverride(
            session_id=session_id,
            tool_call_id=payload.tool_call_id,
            tool_name=matching_call.tool_name,
            decision=payload.decision,
            request_digest_sha256=matching_call.request_digest_sha256,
            should_execute=should_exec,
            effective_payload=res_payload,
            status_message=status_msg,
            operator_id=payload.operator_id,
            resolved_at=utc_now(),
        )
        override_key = f"{ctx.tenant_id}:{session_id}:{payload.tool_call_id}"
        container.resolved_overrides[override_key] = resolved

        await container.audit_ledger.record_intervention(
            ctx=ctx,
            session_id=session_id,
            command=command,
            details={"status_message": status_msg, "tool_call_id": payload.tool_call_id},
        )
        await container.event_bus.publish(
            ctx,
            channel="c2.override_resolved",
            event={
                "session_id": str(session_id),
                "tool_call_id": payload.tool_call_id,
                "tool_name": matching_call.tool_name,
                "decision": payload.decision,
                "status_message": status_msg,
                "should_execute": should_exec,
                "request_digest_sha256": matching_call.request_digest_sha256,
                "effective_payload": res_payload,
            },
        )

        # Atomic auto-resumption: if all pending calls are resolved, resume PAUSED_C2 -> RUNNING
        auto_resumed = False
        remaining = container.pending_tool_calls.get(key, [])
        if payload.auto_resume and len(remaining) == 0:
            with contextlib.suppress(Exception):
                current_sess = await container.control_store.get_session(ctx, session_id)
                if current_sess.status == SessionStatus.PAUSED_C2:
                    await container.c2_state_manager.resume_session(ctx=ctx, session_id=session_id)
                    container.loop_detector.reset_session(str(session_id), tenant_id=ctx.tenant_id)
                    await container.audit_store.append_event(
                        ctx,
                        session_id=session_id,
                        event_type="C2_AUTO_RESUME",
                        payload={
                            "operator_id": payload.operator_id,
                            "trigger_tool_call_id": payload.tool_call_id,
                            "reason": "All pending tool calls resolved; auto-resumed session",
                        },
                    )
                    await container.event_bus.publish(
                        ctx,
                        channel="c2.state_changed",
                        event={
                            "session_id": str(session_id),
                            "new_status": SessionStatus.RUNNING.value,
                            "operator_id": payload.operator_id,
                            "reason": "Auto-resumed after tool override",
                        },
                    )
                    auto_resumed = True

        return {
            "status": "ok",
            "decision": payload.decision,
            "should_execute": should_exec,
            "effective_payload": res_payload,
            "message": status_msg,
            "auto_resumed": auto_resumed,
        }
    except (ValueError, AuthorizationError) as err:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(err)) from err


@router.get("/{session_id}/tool-override/{tool_call_id}", response_model=ResolvedToolOverride)
async def get_resolved_tool_override(
    session_id: uuid.UUID,
    tool_call_id: str,
    ctx: Annotated[TenantContext, Depends(get_tenant_context)],
    container: Annotated[AppContainer, Depends(get_container)],
) -> ResolvedToolOverride:
    """Retrieve the resolved operator decision for an intercepted tool call."""
    key = f"{ctx.tenant_id}:{session_id}:{tool_call_id}"
    resolved = container.resolved_overrides.get(key)
    if resolved is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"No resolved override found for tool call '{tool_call_id}' "
                f"in session '{session_id}'."
            ),
        )
    return resolved


@router.get("/{session_id}/audit-log", response_model=AuditLogResponse)
async def get_session_audit_log(
    session_id: uuid.UUID,
    ctx: Annotated[TenantContext, Depends(get_tenant_context)],
    container: Annotated[AppContainer, Depends(get_container)],
) -> AuditLogResponse:
    """Retrieve and cryptographically verify the SHA-256 hash-chained audit ledger."""
    entries = await container.audit_store.get_session_audit_log(ctx, session_id)
    verified = await container.audit_store.verify_session_chain(ctx, session_id)
    return AuditLogResponse(
        session_id=str(session_id),
        chain_verified=verified,
        entries=entries,
    )


@router.post("/{session_id}/heartbeat", response_model=HeartbeatStatus)
async def worker_heartbeat(
    session_id: uuid.UUID,
    payload: HeartbeatRequest,
    ctx: Annotated[TenantContext, Depends(get_tenant_context)],
    container: Annotated[AppContainer, Depends(get_container)],
) -> HeartbeatStatus:
    """Renew an agent worker lease and return live C2 control directives."""
    return await container.lease_manager.renew_lease(
        ctx=ctx,
        session_id=session_id,
        worker_id=payload.worker_id,
        ttl_seconds=payload.ttl_seconds,
    )


@router.post("/leases/reap", response_model=ReapLeasesResponse)
async def reap_expired_worker_leases(
    ctx: Annotated[TenantContext, Depends(get_tenant_context)],
    container: Annotated[AppContainer, Depends(get_container)],
) -> ReapLeasesResponse:
    """Execute the Dead-Man's Switch reaper on expired worker leases."""
    reaped = await container.lease_manager.reap_expired_leases(ctx=ctx)
    for sid in reaped:
        await container.event_bus.publish(
            ctx,
            channel="c2.lease_expired",
            event={"session_id": str(sid), "new_status": "TERMINATED"},
        )
    return ReapLeasesResponse(
        reaped_session_ids=[str(sid) for sid in reaped],
        reaped_count=len(reaped),
    )
