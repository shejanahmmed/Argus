"""Unit tests for HMAC Bearer Token Auth, W3C Baggage, Lease Reaper, and Fail-Open Spooling."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import timedelta
from pathlib import Path

import pytest

from argus.adapters_infra.in_memory import (
    InMemoryAuditStore,
    InMemoryControlStore,
    InMemoryTraceStore,
)
from argus.c2.lease_manager import C2LeaseManager
from argus.core.errors import AuthorizationError
from argus.core.ids import new_uuid7, utc_now
from argus.core.schemas import (
    AgentFramework,
    AgentSession,
    ArgusSpan,
    OperationName,
    SessionStatus,
    SpanKind,
)
from argus.core.tenancy import Role, TenantContext
from argus.sdk.context import scope_session
from argus.sdk.tracer import ArgusTracer
from argus.security.auth import HmacTokenAuthenticator, parse_w3c_baggage


def test_hmac_token_authenticator_lifecycle() -> None:
    auth = HmacTokenAuthenticator(secret_key="unit-test-secret-key")
    ctx = TenantContext(
        tenant_id="acme_corp",
        workspace_id="prod_eu",
        actor_id="sec_admin",
        role=Role.ADMIN,
    )
    token = auth.issue_token(ctx, ttl_seconds=60, now_epoch=1000)
    verified_ctx = auth.verify_token(token, now_epoch=1030)
    assert verified_ctx == ctx

    # Expired token must raise AuthorizationError
    with pytest.raises(AuthorizationError, match="expired"):
        auth.verify_token(token, now_epoch=1061)

    # Tampered signature must raise AuthorizationError
    tampered = token[:-4] + "0000"
    with pytest.raises(AuthorizationError, match="signature"):
        auth.verify_token(tampered, now_epoch=1030)


def test_parse_w3c_baggage() -> None:
    header = (
        "argus.tenant_id=cyberdyne, argus.workspace_id=skynet;prop=1, "
        "argus.actor_id=t800, argus.role=OPERATOR"
    )
    parsed = parse_w3c_baggage(header)
    assert parsed["argus.tenant_id"] == "cyberdyne"
    assert parsed["argus.workspace_id"] == "skynet"
    assert parsed["argus.actor_id"] == "t800"
    assert parsed["argus.role"] == "OPERATOR"
    assert parse_w3c_baggage(None) == {}


@pytest.mark.asyncio
async def test_c2_lease_manager_and_dead_man_switch() -> None:
    control_store = InMemoryControlStore()
    audit_store = InMemoryAuditStore()
    lease_mgr = C2LeaseManager(control_store=control_store, audit_store=audit_store)

    ctx = TenantContext(
        tenant_id="t_lease",
        workspace_id="w_lease",
        actor_id="worker_node_1",
        role=Role.OPERATOR,
    )
    session_id = new_uuid7()
    session = AgentSession(
        session_id=session_id,
        tenant_id=ctx.tenant_id,
        workspace_id=ctx.workspace_id,
        workflow_id="wf_lease",
        agent_name="worker_agent",
        framework=AgentFramework.AUTOGPT,
        budget_cap_usd=10.0,
    )
    await control_store.create_session(ctx, session)

    t0 = utc_now()
    hb = await lease_mgr.renew_lease(
        ctx,
        session_id=session_id,
        worker_id="pod-alpha-1",
        ttl_seconds=30.0,
        now=t0,
    )
    assert hb.directive == "CONTINUE"
    assert hb.session_status == SessionStatus.RUNNING

    # Before TTL expiration -> nothing reaped
    reaped_early = await lease_mgr.reap_expired_leases(
        ctx, now=t0 + timedelta(seconds=15)
    )
    assert reaped_early == []

    # After TTL expiration -> Dead-Man's Switch transitions session to TERMINATED
    reaped_late = await lease_mgr.reap_expired_leases(
        ctx, now=t0 + timedelta(seconds=31)
    )
    assert reaped_late == [session_id]

    updated_session = await control_store.get_session(ctx, session_id)
    assert updated_session.status == SessionStatus.TERMINATED

    audit_entries = await audit_store.get_session_audit_log(ctx, session_id)
    assert len(audit_entries) == 1
    assert audit_entries[0].event_type == "C2_DEAD_MAN_SWITCH_TERMINATED"
    assert await audit_store.verify_session_chain(ctx, session_id) is True


class _FailingTraceStore(InMemoryTraceStore):
    async def append_spans(self, ctx: TenantContext, spans: Sequence[ArgusSpan]) -> int:
        raise RuntimeError("Simulated ClickHouse storage outage")


@pytest.mark.asyncio
async def test_argus_tracer_fail_open_spool_and_decorator(tmp_path: Path) -> None:
    ctx = TenantContext(
        tenant_id="t_spool",
        workspace_id="w_spool",
        actor_id="agent_1",
        role=Role.OPERATOR,
    )
    spool_file = tmp_path / "spool_spans.jsonl"
    failing_tracer = ArgusTracer(
        trace_store=_FailingTraceStore(),
        spool_path=spool_file,
    )

    session_id = new_uuid7()
    with scope_session(session_id):
        # Must NOT raise even though _FailingTraceStore raises RuntimeError
        async with failing_tracer.start_span(
            ctx,
            name="resilient_step",
            span_kind=SpanKind.AGENT,
            operation_name=OperationName.INVOKE_AGENT,
        ) as builder:
            builder.set_output({"ok": True})

    assert spool_file.exists()
    spooled_lines = spool_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(spooled_lines) == 1
    spooled_span = ArgusSpan.model_validate_json(spooled_lines[0])
    assert spooled_span.name == "resilient_step"

    # Also test @tracer.trace decorator on healthy InMemoryTraceStore
    mem_store = InMemoryTraceStore()
    healthy_tracer = ArgusTracer(trace_store=mem_store, spool_path=None)

    @healthy_tracer.trace(ctx, name="decorated_tool", span_kind=SpanKind.TOOL)
    async def compute_metric(x: int) -> dict[str, int]:
        return {"squared": x * x}

    with scope_session(session_id):
        res = await compute_metric(x=7)
        assert res == {"squared": 49}

    recorded = await mem_store.get_session_spans(ctx, session_id)
    assert len(recorded) == 1
    assert recorded[0].name == "decorated_tool"
    assert recorded[0].output_payload["squared"] == 49
