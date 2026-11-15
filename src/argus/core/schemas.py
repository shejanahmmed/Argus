"""Strict Pydantic v2 domain schemas and deterministic state machines for Argus."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import (
    UUID7,
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from argus.core.errors import InvalidStateTransitionError
from argus.core.ids import parse_dotted_order, utc_now
from argus.core.tenancy import Role

GENESIS_AUDIT_HASH: str = "0" * 64


def compute_canonical_sha256(payload: Any) -> str:
    """Compute a deterministic SHA-256 hex digest over canonicalized JSON."""
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _require_tz_aware(dt: datetime, field_name: str) -> datetime:
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        raise ValueError(f"{field_name} must be a timezone-aware datetime.")
    return dt


class SessionStatus(StrEnum):
    """Lifecycle states of a governed autonomous agent session."""

    RUNNING = "RUNNING"
    PAUSED_C2 = "PAUSED_C2"
    TRIPPED_LOOP = "TRIPPED_LOOP"
    TRIPPED_BUDGET = "TRIPPED_BUDGET"
    COMPLETED = "COMPLETED"
    TERMINATED = "TERMINATED"


VALID_SESSION_TRANSITIONS: dict[SessionStatus, frozenset[SessionStatus]] = {
    SessionStatus.RUNNING: frozenset(
        {
            SessionStatus.PAUSED_C2,
            SessionStatus.TRIPPED_LOOP,
            SessionStatus.TRIPPED_BUDGET,
            SessionStatus.COMPLETED,
            SessionStatus.TERMINATED,
        }
    ),
    SessionStatus.PAUSED_C2: frozenset({SessionStatus.RUNNING, SessionStatus.TERMINATED}),
    SessionStatus.TRIPPED_LOOP: frozenset({SessionStatus.PAUSED_C2, SessionStatus.TERMINATED}),
    SessionStatus.TRIPPED_BUDGET: frozenset({SessionStatus.PAUSED_C2, SessionStatus.TERMINATED}),
    SessionStatus.COMPLETED: frozenset(),
    SessionStatus.TERMINATED: frozenset(),
}


def validate_session_transition(current: SessionStatus, target: SessionStatus) -> None:
    """Enforce legal state transitions in the Argus C2 & Circuit Breaker state machine."""
    allowed = VALID_SESSION_TRANSITIONS.get(current, frozenset())
    if target not in allowed:
        raise InvalidStateTransitionError(current.value, target.value)


class SpanKind(StrEnum):
    """OpenInference-compatible span kinds (`openinference.span.kind`)."""

    AGENT = "AGENT"
    CHAIN = "CHAIN"
    LLM = "LLM"
    TOOL = "TOOL"
    RETRIEVER = "RETRIEVER"
    EMBEDDING = "EMBEDDING"
    GUARDRAIL = "GUARDRAIL"


class OperationName(StrEnum):
    """OpenTelemetry GenAI semantic convention operations (`gen_ai.operation.name`)."""

    INVOKE_AGENT = "invoke_agent"
    CHAT = "chat"
    TEXT_COMPLETION = "text_completion"
    EXECUTE_TOOL = "execute_tool"
    STATE_TRANSITION = "state_transition"
    RETRIEVE = "retrieve"


class AgentFramework(StrEnum):
    """Supported autonomous agent and orchestration frameworks."""

    LANGGRAPH = "langgraph"
    LANGCHAIN = "langchain"
    LCEL = "lcel"
    CREWAI = "crewai"
    AUTOGPT = "autogpt"
    MCP = "mcp"
    CUSTOM = "custom"


class JsonPatchOp(BaseModel):
    """RFC 6902 JSON Patch operation for state diffs and mid-execution C2 memory edits."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    op: Literal["add", "remove", "replace", "move", "copy", "test"]
    path: str = Field(min_length=1, pattern=r"^/.*")
    value: Any = None
    from_path: str | None = Field(
        default=None,
        validation_alias=AliasChoices("from_path", "from"),
        serialization_alias="from",
        pattern=r"^/.*",
    )


class StatePreset(BaseModel):
    """Pre-built state mutation template for one-click C2 interventions."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    preset_id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(min_length=1, max_length=512)
    patches: tuple[JsonPatchOp, ...]
    target_env_override: str | None = None
    recommended_for: tuple[str, ...] = Field(default_factory=tuple)


class ArgusSpan(BaseModel):
    """Unified OpenTelemetry GenAI + OpenInference + LCEL telemetry span contract."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant_id: str = Field(min_length=1, max_length=128)
    workspace_id: str = Field(min_length=1, max_length=128)
    session_id: UUID7
    trace_id: UUID7
    span_id: UUID7
    parent_span_id: UUID7 | None = None
    dotted_order: str = Field(min_length=1)

    name: str = Field(min_length=1, max_length=256)
    span_kind: SpanKind
    operation_name: OperationName
    framework: AgentFramework = Field(default=AgentFramework.CUSTOM)

    model_name: str | None = None
    provider_name: str | None = None
    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    cost_usd: float = Field(default=0.0, ge=0.0)
    ttft_ms: float | None = Field(default=None, ge=0.0)
    latency_ms: float = Field(default=0.0, ge=0.0)

    input_payload: dict[str, Any] = Field(default_factory=dict)
    output_payload: dict[str, Any] = Field(default_factory=dict)
    state_diff: tuple[JsonPatchOp, ...] = Field(default_factory=tuple)
    attributes: dict[str, str | int | float | bool] = Field(default_factory=dict)
    redacted: bool = Field(default=False)

    started_at: datetime
    ended_at: datetime | None = None

    @field_validator("started_at")
    @classmethod
    def _validate_started_at(cls, v: datetime) -> datetime:
        return _require_tz_aware(v, "started_at")

    @field_validator("ended_at")
    @classmethod
    def _validate_ended_at(cls, v: datetime | None) -> datetime | None:
        if v is not None:
            return _require_tz_aware(v, "ended_at")
        return None

    @model_validator(mode="after")
    def _validate_hierarchy_and_timing(self) -> ArgusSpan:
        if self.ended_at is not None and self.ended_at < self.started_at:
            raise ValueError("ended_at cannot be earlier than started_at.")

        parsed = parse_dotted_order(self.dotted_order)
        _leaf_ts, leaf_uid = parsed[-1]
        if leaf_uid != self.span_id:
            raise ValueError(
                f"dotted_order leaf UUID ({leaf_uid}) must match span_id ({self.span_id})."
            )

        if self.parent_span_id is None and len(parsed) != 1:
            raise ValueError("Root span (parent_span_id=None) must have a 1-segment dotted_order.")
        if self.parent_span_id is not None:
            if len(parsed) < 2:
                raise ValueError(
                    "Child span with parent_span_id must have at least 2 dotted_order segments."
                )
            parent_uid = parsed[-2][1]
            if parent_uid != self.parent_span_id:
                raise ValueError(
                    f"dotted_order parent UUID ({parent_uid}) must match "
                    f"parent_span_id ({self.parent_span_id})."
                )
        return self


class AgentSession(BaseModel):
    """Top-level execution container tracking state, budget, and governance status."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    session_id: UUID7
    tenant_id: str = Field(min_length=1, max_length=128)
    workspace_id: str = Field(min_length=1, max_length=128)
    workflow_id: str = Field(min_length=1, max_length=128)
    agent_name: str = Field(min_length=1, max_length=128)
    framework: AgentFramework
    status: SessionStatus = Field(default=SessionStatus.RUNNING)

    budget_cap_usd: float = Field(gt=0.0)
    accumulated_cost_usd: float = Field(default=0.0, ge=0.0)
    latest_checkpoint_id: UUID7 | None = None

    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("created_at", "updated_at")
    @classmethod
    def _validate_timestamps(cls, v: datetime) -> datetime:
        return _require_tz_aware(v, "session timestamp")

    def transition_to(
        self,
        next_status: SessionStatus,
        *,
        updated_at: datetime | None = None,
    ) -> AgentSession:
        """Return a new AgentSession with validated state transition."""
        validate_session_transition(self.status, next_status)
        ts = updated_at if updated_at is not None else utc_now()
        return self.model_copy(update={"status": next_status, "updated_at": ts})


class PendingToolCall(BaseModel):
    """Intercepted MCP or framework tool call awaiting governance or C2 review."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tool_call_id: str = Field(min_length=1, max_length=128)
    tool_name: str = Field(min_length=1, max_length=256)
    tool_args: dict[str, Any] = Field(default_factory=dict)
    is_destructive: bool = Field(default=False)
    security_risk: str | None = Field(default=None)
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("created_at")
    @classmethod
    def _validate_created_at(cls, v: datetime) -> datetime:
        return _require_tz_aware(v, "created_at")

    @property
    def request_digest_sha256(self) -> str:
        """Cryptographic digest binding tool name and arguments against mid-approval tampering."""
        return compute_canonical_sha256(
            {
                "tool_call_id": self.tool_call_id,
                "tool_name": self.tool_name,
                "tool_args": self.tool_args,
            }
        )


class CheckpointRecord(BaseModel):
    """Versioned agent state snapshot supporting optimistic concurrency locks."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    checkpoint_id: UUID7
    parent_checkpoint_id: UUID7 | None = None
    tenant_id: str = Field(min_length=1, max_length=128)
    workspace_id: str = Field(min_length=1, max_length=128)
    session_id: UUID7
    node_name: str = Field(min_length=1, max_length=128)
    step_index: int = Field(ge=0)
    memory_state: dict[str, Any] = Field(default_factory=dict)
    pending_tool_call: PendingToolCall | None = None
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("created_at")
    @classmethod
    def _validate_created_at(cls, v: datetime) -> datetime:
        return _require_tz_aware(v, "created_at")


class ToolOverrideSpec(BaseModel):
    """Operator decision for an intercepted tool call during PAUSED_C2."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    decision: Literal["approve", "edit", "reject", "mock"]
    request_digest_sha256: str = Field(min_length=64, max_length=64)
    modified_args: dict[str, Any] | None = None
    mock_output: dict[str, Any] | None = None
    rejection_reason: str | None = None

    @model_validator(mode="after")
    def _validate_decision_payload(self) -> ToolOverrideSpec:
        if self.decision == "edit" and self.modified_args is None:
            raise ValueError("modified_args is required when decision is 'edit'.")
        if self.decision == "mock" and self.mock_output is None:
            raise ValueError("mock_output is required when decision is 'mock'.")
        return self


class ResolvedToolOverride(BaseModel):
    """Immutable record of an operator's override decision for an intercepted tool call."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    session_id: UUID7
    tool_call_id: str = Field(min_length=1, max_length=128)
    tool_name: str = Field(min_length=1, max_length=256)
    decision: Literal["approve", "edit", "mock", "reject"]
    request_digest_sha256: str = Field(min_length=64, max_length=64)
    should_execute: bool
    effective_payload: dict[str, Any] = Field(default_factory=dict)
    status_message: str
    operator_id: str = Field(min_length=1, max_length=128)
    resolved_at: datetime = Field(default_factory=utc_now)

    @field_validator("resolved_at")
    @classmethod
    def _validate_resolved_at(cls, v: datetime) -> datetime:
        return _require_tz_aware(v, "resolved_at")


class C2OverrideCommand(BaseModel):
    """Distributed Command & Control intervention payload issued by a human operator."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    command_id: UUID7
    tenant_id: str = Field(min_length=1, max_length=128)
    workspace_id: str = Field(min_length=1, max_length=128)
    session_id: UUID7
    expected_checkpoint_id: UUID7
    operator_id: str = Field(min_length=1, max_length=128)
    operator_role: Literal[Role.OPERATOR, Role.ADMIN]
    action: Literal["RESUME", "EDIT_MEMORY", "OVERRIDE_TOOL_CALL", "TERMINATE"]
    memory_patch: tuple[JsonPatchOp, ...] = Field(default_factory=tuple)
    tool_override: ToolOverrideSpec | None = None
    reason: str = Field(min_length=1, max_length=512)
    issued_at: datetime = Field(default_factory=utc_now)

    @field_validator("issued_at")
    @classmethod
    def _validate_issued_at(cls, v: datetime) -> datetime:
        return _require_tz_aware(v, "issued_at")

    @model_validator(mode="after")
    def _validate_action_requirements(self) -> C2OverrideCommand:
        if self.action == "EDIT_MEMORY" and not self.memory_patch:
            raise ValueError("memory_patch cannot be empty when action is 'EDIT_MEMORY'.")
        if self.action == "OVERRIDE_TOOL_CALL" and self.tool_override is None:
            raise ValueError("tool_override is required when action is 'OVERRIDE_TOOL_CALL'.")
        return self


class CircuitBreakerReason(StrEnum):
    """Classification of why the automated circuit breaker tripped."""

    NONE = "NONE"
    EXACT_TOOL_LOOP = "EXACT_TOOL_LOOP"
    STATE_OSCILLATION = "STATE_OSCILLATION"
    SEMANTIC_STAGNATION = "SEMANTIC_STAGNATION"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    SECURITY_VIOLATION = "SECURITY_VIOLATION"
    HIGH_RISK_TOOL = "HIGH_RISK_TOOL"


class CircuitBreakerAction(StrEnum):
    """Remediation directive emitted by the circuit breaker engine."""

    ALLOW = "ALLOW"
    NUDGE_BACKTRACK = "NUDGE_BACKTRACK"
    PAUSE_FOR_C2 = "PAUSE_FOR_C2"
    TERMINATE = "TERMINATE"


class CircuitBreakerVerdict(BaseModel):
    """Result of evaluating a proposed agent step against the 3-tier loop and budget breaker."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tripped: bool
    reason: CircuitBreakerReason = Field(default=CircuitBreakerReason.NONE)
    similarity_score: float = Field(default=0.0, ge=0.0, le=1.0)
    hamming_distance: int | None = Field(default=None, ge=0, le=64)
    repeated_count: int = Field(default=0, ge=0)
    accumulated_cost_usd: float = Field(default=0.0, ge=0.0)
    budget_limit_usd: float = Field(gt=0.0)
    wasted_cost_usd: float = Field(default=0.0, ge=0.0)
    recommended_action: CircuitBreakerAction = Field(default=CircuitBreakerAction.ALLOW)
    diagnostic_message: str = Field(default="")
    nudge_instruction: str | None = Field(default=None)
    trip_tier: int | None = Field(default=None, ge=1, le=3)


class WorkflowROIAttribution(BaseModel):
    """Exact financial ROI attribution mapping LLM/tool/infra costs against task completion."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant_id: str = Field(min_length=1, max_length=128)
    workspace_id: str = Field(min_length=1, max_length=128)
    workflow_id: str = Field(min_length=1, max_length=128)
    session_id: UUID7

    task_completed: bool
    task_completion_score: float = Field(ge=0.0, le=1.0)
    tool_correctness_score: float = Field(ge=0.0, le=1.0)

    llm_cost_usd: float = Field(ge=0.0)
    tool_cost_usd: float = Field(default=0.0, ge=0.0)
    infra_cost_usd: float = Field(default=0.0, ge=0.0)
    c2_intervention_cost_usd: float = Field(default=0.0, ge=0.0)
    wasted_loop_cost_usd: float = Field(default=0.0, ge=0.0)
    total_cost_usd: float = Field(ge=0.0)

    assigned_business_value_usd: float = Field(ge=0.0)
    realized_business_value_usd: float = Field(default=0.0, ge=0.0)
    net_roi_usd: float
    roi_percentage: float

    # Operational metrics
    wall_clock_duration_seconds: float = Field(default=0.0, ge=0.0)
    c2_interventions_count: int = Field(default=0, ge=0)
    total_spans_evaluated: int = Field(default=0, ge=0)

    @classmethod
    def calculate(
        cls,
        *,
        tenant_id: str,
        workspace_id: str,
        workflow_id: str,
        session_id: UUID7,
        task_completed: bool,
        task_completion_score: float,
        tool_correctness_score: float,
        llm_cost_usd: float,
        tool_cost_usd: float = 0.0,
        infra_cost_usd: float = 0.0,
        c2_intervention_cost_usd: float = 0.0,
        wasted_loop_cost_usd: float = 0.0,
        assigned_business_value_usd: float,
        wall_clock_duration_seconds: float = 0.0,
        c2_interventions_count: int = 0,
        total_spans_evaluated: int = 0,
    ) -> WorkflowROIAttribution:
        """Compute deterministic financial ROI from component cost logs and completion status."""
        total_cost = round(
            llm_cost_usd + tool_cost_usd + infra_cost_usd + c2_intervention_cost_usd,
            8,
        )
        realized_value = (
            round(assigned_business_value_usd * task_completion_score, 8)
            if task_completed
            else 0.0
        )
        net_roi = round(realized_value - total_cost, 8)
        roi_pct = round((net_roi / total_cost) * 100.0, 4) if total_cost > 0.0 else 0.0

        return cls(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            workflow_id=workflow_id,
            session_id=session_id,
            task_completed=task_completed,
            task_completion_score=task_completion_score,
            tool_correctness_score=tool_correctness_score,
            llm_cost_usd=llm_cost_usd,
            tool_cost_usd=tool_cost_usd,
            infra_cost_usd=infra_cost_usd,
            c2_intervention_cost_usd=c2_intervention_cost_usd,
            wasted_loop_cost_usd=wasted_loop_cost_usd,
            total_cost_usd=total_cost,
            assigned_business_value_usd=assigned_business_value_usd,
            realized_business_value_usd=realized_value,
            net_roi_usd=net_roi,
            roi_percentage=roi_pct,
            wall_clock_duration_seconds=wall_clock_duration_seconds,
            c2_interventions_count=c2_interventions_count,
            total_spans_evaluated=total_spans_evaluated,
        )


class TrajectoryEvaluationReport(BaseModel):
    """Deterministic evaluation report for an autonomous agent execution trajectory."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    session_id: UUID7
    tenant_id: str = Field(min_length=1, max_length=128)
    workspace_id: str = Field(min_length=1, max_length=128)
    total_steps: int = Field(ge=0)
    llm_steps: int = Field(default=0, ge=0)
    tool_steps: int = Field(default=0, ge=0)

    # Tool selection metrics
    expected_tools: list[str] = Field(default_factory=list)
    used_tools: list[str] = Field(default_factory=list)
    matched_tools: list[str] = Field(default_factory=list)
    missing_tools: list[str] = Field(default_factory=list)
    unexpected_tools: list[str] = Field(default_factory=list)
    tool_correctness_score: float = Field(ge=0.0, le=1.0)

    # Task completion metrics
    goal_keywords: list[str] = Field(default_factory=list)
    matched_keywords: list[str] = Field(default_factory=list)
    task_completed: bool
    task_completion_score: float = Field(ge=0.0, le=1.0)
    fatal_errors_detected: list[str] = Field(default_factory=list)
    diagnostic_summary: str = Field(default="")


class FleetROISummary(BaseModel):
    """Aggregated financial ROI and performance metrics across the governed agent fleet."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant_id: str = Field(min_length=1, max_length=128)
    workspace_id: str = Field(min_length=1, max_length=128)
    total_sessions: int = Field(ge=0)
    completed_sessions: int = Field(ge=0)
    total_fleet_spend_usd: float = Field(ge=0.0)
    total_realized_value_usd: float = Field(ge=0.0)
    net_fleet_roi_usd: float
    fleet_roi_percentage: float
    total_wasted_loop_cost_usd: float = Field(default=0.0, ge=0.0)
    average_completion_score: float = Field(default=0.0, ge=0.0, le=1.0)
    average_tool_score: float = Field(default=0.0, ge=0.0, le=1.0)
    sessions: list[WorkflowROIAttribution] = Field(default_factory=list)


class AuditLogEntry(BaseModel):
    """Append-only SHA-256 hash-chained audit record for governance and C2 compliance."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    audit_id: UUID7
    tenant_id: str = Field(min_length=1, max_length=128)
    workspace_id: str = Field(min_length=1, max_length=128)
    session_id: UUID7
    actor_id: str = Field(min_length=1, max_length=128)
    actor_role: Role
    event_type: str = Field(min_length=1, max_length=128)
    payload: dict[str, Any] = Field(default_factory=dict)
    payload_sha256: str = Field(min_length=64, max_length=64)
    prev_entry_hash: str = Field(default=GENESIS_AUDIT_HASH, min_length=64, max_length=64)
    entry_hash: str = Field(min_length=64, max_length=64)
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("created_at")
    @classmethod
    def _validate_created_at(cls, v: datetime) -> datetime:
        return _require_tz_aware(v, "created_at")

    @classmethod
    def create_linked(
        cls,
        *,
        audit_id: UUID7,
        tenant_id: str,
        workspace_id: str,
        session_id: UUID7,
        actor_id: str,
        actor_role: Role,
        event_type: str,
        payload: dict[str, Any],
        prev_entry_hash: str = GENESIS_AUDIT_HASH,
        created_at: datetime | None = None,
    ) -> AuditLogEntry:
        """Construct a cryptographically linked AuditLogEntry from the previous chain hash."""
        ts = created_at if created_at is not None else utc_now()
        _require_tz_aware(ts, "created_at")
        payload_digest = compute_canonical_sha256(payload)
        envelope = {
            "audit_id": str(audit_id),
            "tenant_id": tenant_id,
            "workspace_id": workspace_id,
            "session_id": str(session_id),
            "actor_id": actor_id,
            "actor_role": actor_role.value,
            "event_type": event_type,
            "payload_sha256": payload_digest,
            "prev_entry_hash": prev_entry_hash,
            "created_at": ts.isoformat(),
        }
        entry_digest = compute_canonical_sha256(envelope)
        return cls(
            audit_id=audit_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            session_id=session_id,
            actor_id=actor_id,
            actor_role=actor_role,
            event_type=event_type,
            payload=payload,
            payload_sha256=payload_digest,
            prev_entry_hash=prev_entry_hash,
            entry_hash=entry_digest,
            created_at=ts,
        )

    def check_integrity_detailed(
        self, expected_prev_hash: str
    ) -> tuple[bool, AuditViolationType | None, str | None]:
        """Verify block integrity and return specific violation diagnostic if tampered."""
        if self.prev_entry_hash != expected_prev_hash:
            if expected_prev_hash == GENESIS_AUDIT_HASH:
                msg_gen = (
                    f"Genesis hash violation: expected '{GENESIS_AUDIT_HASH}', "
                    f"got '{self.prev_entry_hash}'."
                )
                return False, AuditViolationType.GENESIS_VIOLATION, msg_gen
            msg_link = (
                f"Chain link broken: expected prev_hash '{expected_prev_hash}', "
                f"got '{self.prev_entry_hash}'."
            )
            return False, AuditViolationType.CHAIN_LINK_BROKEN, msg_link
        computed_payload = compute_canonical_sha256(self.payload)
        if computed_payload != self.payload_sha256:
            msg_pay = (
                f"Payload altered: expected digest '{self.payload_sha256}', "
                f"computed '{computed_payload}'."
            )
            return False, AuditViolationType.PAYLOAD_DIGEST_MISMATCH, msg_pay
        envelope = {
            "audit_id": str(self.audit_id),
            "tenant_id": self.tenant_id,
            "workspace_id": self.workspace_id,
            "session_id": str(self.session_id),
            "actor_id": self.actor_id,
            "actor_role": self.actor_role.value,
            "event_type": self.event_type,
            "payload_sha256": self.payload_sha256,
            "prev_entry_hash": self.prev_entry_hash,
            "created_at": self.created_at.isoformat(),
        }
        computed_envelope = compute_canonical_sha256(envelope)
        if computed_envelope != self.entry_hash:
            msg_env = (
                f"Envelope altered: expected hash '{self.entry_hash}', "
                f"computed '{computed_envelope}'."
            )
            return False, AuditViolationType.ENVELOPE_DIGEST_MISMATCH, msg_env
        return True, None, None

    def verify_integrity(self, expected_prev_hash: str) -> bool:
        """Recompute payload and envelope SHA-256 digests to detect any tampering."""
        is_valid, _, _ = self.check_integrity_detailed(expected_prev_hash)
        return is_valid


class AuditViolationType(StrEnum):
    """Categorized cryptographic violation reasons when audit chain tampering occurs."""

    GENESIS_VIOLATION = "GENESIS_VIOLATION"
    PAYLOAD_DIGEST_MISMATCH = "PAYLOAD_DIGEST_MISMATCH"
    ENVELOPE_DIGEST_MISMATCH = "ENVELOPE_DIGEST_MISMATCH"
    CHAIN_LINK_BROKEN = "CHAIN_LINK_BROKEN"


class AuditVerificationResult(BaseModel):
    """Detailed cryptographic audit chain verification report for compliance attestation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    session_id: uuid.UUID
    is_valid: bool
    total_entries: int
    genesis_hash: str = Field(default=GENESIS_AUDIT_HASH)
    tip_hash: str | None = None
    tampered_entry_index: int | None = None
    tampered_audit_id: uuid.UUID | None = None
    violation_type: AuditViolationType | None = None
    violation_details: str | None = None
    verified_at: datetime = Field(default_factory=utc_now)


class AuditLogResponse(BaseModel):
    """Response envelope for audit log retrieval and cryptographic verification."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    session_id: str
    chain_verified: bool
    entries: list[AuditLogEntry]
    verification_report: AuditVerificationResult | None = None


class AuditQueryResponse(BaseModel):
    """Paginated search response for tenant compliance audit entries."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    entries: list[AuditLogEntry]
    total_count: int
    limit: int
    offset: int


class IssueTokenRequest(BaseModel):
    """Payload to request an HMAC Bearer token for an actor or agent worker."""

    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9_\-]+$")
    workspace_id: str = Field(min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9_\-]+$")
    actor_id: str = Field(min_length=1, max_length=128)
    role: Role = Field(default=Role.OPERATOR)
    ttl_seconds: int = Field(default=86400, ge=60, le=31536000)


class IssueTokenResponse(BaseModel):
    """Cryptographic Bearer token issued for an actor."""

    model_config = ConfigDict(extra="forbid")

    token: str
    tenant_id: str
    workspace_id: str
    actor_id: str
    role: Role
    expires_at_epoch: int

