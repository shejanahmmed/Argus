"""Unit tests for the enterprise 3-tier loop detector circuit breaker."""

from __future__ import annotations

from argus.core.schemas import CircuitBreakerAction, CircuitBreakerReason
from argus.governance.loop_detector import LoopDetector


def test_loop_detector_tier1_exact_repetition() -> None:
    detector = LoopDetector(max_exact_repetitions=3)
    session_id = "test_session_1"

    # Turn 1: normal call ($0.005)
    v1 = detector.evaluate_step(
        session_id=session_id,
        tool_name="query_db",
        tool_args={"user_id": 42},
        step_cost_usd=0.005,
    )
    assert not v1.tripped
    assert v1.recommended_action == CircuitBreakerAction.ALLOW

    # Turn 2: identical call ($0.005)
    v2 = detector.evaluate_step(
        session_id=session_id,
        tool_name="query_db",
        tool_args={"user_id": 42},
        step_cost_usd=0.005,
    )
    assert not v2.tripped

    # Turn 3: 3rd identical call trips Tier 1 breaker ($0.005)
    v3 = detector.evaluate_step(
        session_id=session_id,
        tool_name="query_db",
        tool_args={"user_id": 42},
        step_cost_usd=0.005,
    )
    assert v3.tripped
    assert v3.trip_tier == 1
    assert v3.reason == CircuitBreakerReason.EXACT_TOOL_LOOP
    assert v3.recommended_action == CircuitBreakerAction.PAUSE_FOR_C2
    assert v3.repeated_count == 3
    assert v3.hamming_distance == 0
    # Wasted cost must aggregate all 3 repeated identical calls: 3 * 0.005 = 0.015
    assert abs(v3.wasted_cost_usd - 0.015) < 1e-6


def test_loop_detector_tier2_oscillatory_loop() -> None:
    detector = LoopDetector(max_oscillations=2)
    session_id = "test_session_2"

    # Sequence: ToolA -> ToolB -> ToolA -> ToolB (Cycle of length 2 repeated 2 times)
    detector.evaluate_step(
        session_id=session_id, tool_name="tool_a", tool_args={"x": 1}, step_cost_usd=0.002
    )
    detector.evaluate_step(
        session_id=session_id, tool_name="tool_b", tool_args={"y": 2}, step_cost_usd=0.003
    )
    detector.evaluate_step(
        session_id=session_id, tool_name="tool_a", tool_args={"x": 1}, step_cost_usd=0.002
    )

    v_trip = detector.evaluate_step(
        session_id=session_id, tool_name="tool_b", tool_args={"y": 2}, step_cost_usd=0.003
    )
    assert v_trip.tripped
    assert v_trip.trip_tier == 2
    assert v_trip.reason == CircuitBreakerReason.STATE_OSCILLATION
    assert v_trip.recommended_action == CircuitBreakerAction.PAUSE_FOR_C2
    assert v_trip.repeated_count == 2
    assert abs(v_trip.wasted_cost_usd - 0.010) < 1e-6


def test_loop_detector_tier2_simhash_volatile_arguments() -> None:
    detector = LoopDetector(max_oscillations=2, simhash_max_hamming=3)
    session_id = "test_session_simhash"

    # Cycle of ToolA -> ToolB -> ToolA -> ToolB with volatile argument differences
    # Step 1: ToolA with ts=100
    detector.evaluate_step(
        session_id=session_id,
        tool_name="fetch_transactions",
        tool_args={"account": "acc_99", "limit": 50, "ts": 100},
        step_cost_usd=0.004,
    )
    # Step 2: ToolB with ts=101
    detector.evaluate_step(
        session_id=session_id,
        tool_name="verify_balance",
        tool_args={"account": "acc_99", "currency": "USD", "ts": 101},
        step_cost_usd=0.002,
    )
    # Step 3: ToolA with ts=102 (near-duplicate of step 1)
    detector.evaluate_step(
        session_id=session_id,
        tool_name="fetch_transactions",
        tool_args={"account": "acc_99", "limit": 50, "ts": 102},
        step_cost_usd=0.004,
    )
    # Step 4: ToolB with ts=103 (near-duplicate of step 2) -> Trips Tier 2 via SimHash!
    v_trip = detector.evaluate_step(
        session_id=session_id,
        tool_name="verify_balance",
        tool_args={"account": "acc_99", "currency": "USD", "ts": 103},
        step_cost_usd=0.002,
    )
    assert v_trip.tripped
    assert v_trip.trip_tier == 2
    assert v_trip.reason == CircuitBreakerReason.STATE_OSCILLATION
    assert v_trip.recommended_action == CircuitBreakerAction.PAUSE_FOR_C2
    assert v_trip.hamming_distance is not None and v_trip.hamming_distance <= 3
    assert abs(v_trip.wasted_cost_usd - 0.012) < 1e-6


def test_loop_detector_tier3_semantic_stagnation_and_nudge() -> None:
    detector = LoopDetector(
        semantic_threshold=0.65,
        max_semantic_repetitions=2,
        window_size=10,
    )
    session_id = "test_session_3"

    # 3 paraphrased thoughts conveying identical reasoning intent
    t1 = "I need to check the active subscription records for user 452 in the database."
    t2 = "Let me check the database again for active subscriptions belonging to user 452."
    t3 = "I will perform a check on the database for user 452 active subscriptions."

    r1 = detector.evaluate_step(session_id=session_id, thought_text=t1, step_cost_usd=0.001)
    assert not r1.tripped

    r2 = detector.evaluate_step(session_id=session_id, thought_text=t2, step_cost_usd=0.001)
    assert not r2.tripped

    # 3rd step trips Tier 3 semantic stagnation with NUDGE_BACKTRACK
    r3 = detector.evaluate_step(session_id=session_id, thought_text=t3, step_cost_usd=0.001)
    assert r3.tripped
    assert r3.trip_tier == 3
    assert r3.reason == CircuitBreakerReason.SEMANTIC_STAGNATION
    assert r3.recommended_action == CircuitBreakerAction.NUDGE_BACKTRACK
    assert r3.similarity_score >= 0.65
    assert r3.nudge_instruction is not None
    assert "[ARGUS CIRCUIT BREAKER]" in r3.nudge_instruction
    assert "Reasoning stagnation detected" in r3.nudge_instruction


def test_loop_detector_tier3_escalation_to_pause() -> None:
    detector = LoopDetector(
        semantic_threshold=0.65,
        max_semantic_repetitions=2,
        window_size=10,
    )
    session_id = "test_session_escalation"

    t1 = "I need to check the active subscription records for user 452 in the database."
    t2 = "Let me check the database again for active subscriptions belonging to user 452."
    t3 = "I will perform a check on the database for user 452 active subscriptions."

    detector.evaluate_step(session_id=session_id, thought_text=t1)
    detector.evaluate_step(session_id=session_id, thought_text=t2)

    # First trip returns NUDGE_BACKTRACK
    trip1 = detector.evaluate_step(session_id=session_id, thought_text=t3)
    assert trip1.tripped
    assert trip1.recommended_action == CircuitBreakerAction.NUDGE_BACKTRACK

    # Agent disregards nudge and submits 4th stagnant thought -> Escalates to PAUSE_FOR_C2!
    t4 = "I will check the active subscription records for user 452 in the database again."
    trip2 = detector.evaluate_step(session_id=session_id, thought_text=t4)
    assert trip2.tripped
    assert trip2.trip_tier == 3
    assert trip2.recommended_action == CircuitBreakerAction.PAUSE_FOR_C2
    assert "Consecutive semantic stagnation after backtrack nudge" in trip2.diagnostic_message


def test_loop_detector_multi_tenant_isolation() -> None:
    detector = LoopDetector(max_exact_repetitions=2)
    session_id = "shared_session_uuid"

    # Tenant A executes step 1
    va1 = detector.evaluate_step(
        session_id=session_id,
        tenant_id="tenant_a",
        tool_name="delete_table",
    )
    assert not va1.tripped

    # Tenant B executes step 1 with same session ID string -> Must NOT trip!
    vb1 = detector.evaluate_step(
        session_id=session_id,
        tenant_id="tenant_b",
        tool_name="delete_table",
    )
    assert not vb1.tripped

    # Tenant A executes step 2 -> Trips Tenant A only
    va2 = detector.evaluate_step(
        session_id=session_id,
        tenant_id="tenant_a",
        tool_name="delete_table",
    )
    assert va2.tripped

    # Resetting Tenant A does not reset Tenant B
    detector.reset_session(session_id, tenant_id="tenant_a")
    va_after = detector.evaluate_step(
        session_id=session_id,
        tenant_id="tenant_a",
        tool_name="delete_table",
    )
    assert not va_after.tripped


def test_loop_detector_bounded_lru_eviction() -> None:
    # Cap capacity to 5 sessions
    detector = LoopDetector(max_tracked_sessions=5, max_exact_repetitions=2)

    for i in range(10):
        detector.evaluate_step(session_id=f"sess_{i}", tool_name="fetch_record")

    # History dictionary must not exceed max_tracked_sessions
    assert len(detector._history) == 5
    # Oldest sessions (0..4) should have been evicted
    assert "sess_0" not in detector._history
    assert "sess_1" not in detector._history
    assert "sess_9" in detector._history


def test_loop_detector_resets_session_properly() -> None:
    detector = LoopDetector(max_exact_repetitions=2)
    session_id = "test_reset"

    detector.evaluate_step(session_id=session_id, tool_name="fetch_status")
    detector.reset_session(session_id)

    # Next call should be treated as step 1 again, not step 2
    verdict = detector.evaluate_step(session_id=session_id, tool_name="fetch_status")
    assert not verdict.tripped
