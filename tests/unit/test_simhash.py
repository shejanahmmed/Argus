"""Unit tests for pure-Python 64-bit SimHash locality-sensitive hashing."""

from __future__ import annotations

from argus.governance.simhash import (
    compute_simhash64,
    extract_features,
    fnv1a_64,
    hamming_distance64,
    payload_simhash,
    simhash_similarity,
)


def test_fnv1a_64_deterministic() -> None:
    h1 = fnv1a_64("query_database")
    h2 = fnv1a_64("query_database")
    assert h1 == h2
    assert 0 <= h1 <= 0xFFFFFFFFFFFFFFFF
    assert fnv1a_64("different_token") != h1


def test_simhash_exact_match() -> None:
    text = "SELECT * FROM orders WHERE status = 'pending' AND total > 100"
    h1 = payload_simhash(text)
    h2 = payload_simhash(text)
    assert h1 == h2
    assert hamming_distance64(h1, h2) == 0
    assert simhash_similarity(h1, h2) == 1.0


def test_simhash_near_duplicate_volatile_args() -> None:
    # Two SQL tool payloads differing only by timestamp and session ID
    p1 = {
        "sql": "SELECT * FROM audit_logs WHERE user_id = 452 ORDER BY ts DESC LIMIT 10",
        "timestamp": 1731600001,
        "session_nonce": "9a1b2c",
    }
    p2 = {
        "sql": "SELECT * FROM audit_logs WHERE user_id = 452 ORDER BY ts DESC LIMIT 10",
        "timestamp": 1731600002,
        "session_nonce": "9a1b2d",
    }
    h1 = payload_simhash(p1)
    h2 = payload_simhash(p2)
    dist = hamming_distance64(h1, h2)
    # Volatile fields produce minor bit difference; distance must be <= 3 (similarity >= 0.95)
    assert dist <= 3
    assert simhash_similarity(h1, h2) >= 0.95


def test_simhash_distinct_payloads() -> None:
    p1 = "Search document repository for employee healthcare enrollment policies"
    p2 = "Calculate aggregate quarterly sales tax deductions for Q3 fiscal year"
    h1 = payload_simhash(p1)
    h2 = payload_simhash(p2)
    dist = hamming_distance64(h1, h2)
    # Distinct topics should have high Hamming distance (typically >= 15 bits)
    assert dist >= 15
    assert simhash_similarity(h1, h2) < 0.80


def test_simhash_empty_payload() -> None:
    assert compute_simhash64([]) == 0
    assert payload_simhash("") == 0
    assert extract_features("") == []
