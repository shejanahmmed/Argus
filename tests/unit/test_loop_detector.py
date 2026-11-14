"""Unit tests for the 3-tier loop detector circuit breaker."""

from __future__ import annotations

from argus.core.schemas import CircuitBreakerAction, CircuitBreakerReason
from argus.governance.loop_detector import LoopDetector


def test_loop_detector_tier1_exact_repetition() -> None:
    detector = LoopDetector(max_exact_repetitions=3)
    session_id = "test_session_1"

    # Turn 1: normal call
    v1 = detector.evaluate_step(
        session_id=session_id,
        tool_name="query_db",
        tool_args={"user_id": 42},
    )
    assert not v1.tripped
    assert v1.recommended_action == CircuitBreakerAction.ALLOW

    # Turn 2: identical call (allowed within threshold)
    v2 = detector.evaluate_step(
        session_id=session_id,
        tool_name="query_db",
        tool_args={"user_id": 42},
    )
    assert not v2.tripped

    # Turn 3: 3rd identical call trips Tier 1 breaker
    v3 = detector.evaluate_step(
        session_id=session_id,
        tool_name="query_db",
        tool_args={"user_id": 42},
    )
    assert v3.tripped
    assert v3.reason == CircuitBreakerReason.EXACT_TOOL_LOOP
    assert v3.recommended_action == CircuitBreakerAction.PAUSE_FOR_C2
    assert v3.repeated_count == 3


def test_loop_detector_tier2_oscillatory_loop() -> None:
    detector = LoopDetector(max_oscillations=2)
    session_id = "test_session_2"

    # Sequence: ToolA -> ToolB -> ToolA -> ToolB (Cycle of length 2 repeated 2 times)
    detector.evaluate_step(session_id=session_id, tool_name="tool_a", tool_args={"x": 1})
    detector.evaluate_step(session_id=session_id, tool_name="tool_b", tool_args={"y": 2})
    detector.evaluate_step(session_id=session_id, tool_name="tool_a", tool_args={"x": 1})

    v_trip = detector.evaluate_step(session_id=session_id, tool_name="tool_b", tool_args={"y": 2})
    assert v_trip.tripped
    assert v_trip.reason == CircuitBreakerReason.STATE_OSCILLATION
    assert v_trip.recommended_action == CircuitBreakerAction.PAUSE_FOR_C2


def test_loop_detector_tier3_semantic_stagnation() -> None:
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

    r1 = detector.evaluate_step(session_id=session_id, thought_text=t1)
    assert not r1.tripped

    r2 = detector.evaluate_step(session_id=session_id, thought_text=t2)
    assert not r2.tripped

    r3 = detector.evaluate_step(session_id=session_id, thought_text=t3)
    assert r3.tripped
    assert r3.reason == CircuitBreakerReason.SEMANTIC_STAGNATION
    assert r3.recommended_action == CircuitBreakerAction.NUDGE_BACKTRACK
    assert r3.similarity_score >= 0.65


def test_loop_detector_resets_session_properly() -> None:
    detector = LoopDetector(max_exact_repetitions=2)
    session_id = "test_reset"

    detector.evaluate_step(session_id=session_id, tool_name="fetch_status")
    detector.reset_session(session_id)

    # Next call should be treated as step 1 again, not step 2
    verdict = detector.evaluate_step(session_id=session_id, tool_name="fetch_status")
    assert not verdict.tripped
