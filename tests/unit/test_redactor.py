"""Unit tests for EdgeRedactor PII and credential scrubbing."""

from __future__ import annotations

from typing import Any

from argus.security.redactor import MAX_DEPTH_TOKEN, REDACTED_TOKEN, EdgeRedactor


def test_redactor_scrubs_sensitive_keys_and_values_without_mutating_input() -> None:
    redactor = EdgeRedactor()
    original: dict[str, Any] = {
        "api_key": "plain-secret-value",
        "nested": {
            "prompt": (
                "Contact alice.smith@example.com or use key "
                "sk-proj-1234567890abcdefghijklmnop and SSN 123-45-6789."
            ),
            "Authorization": "Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abc123def456",
            "safe_number": 42,
        },
    }

    scrubbed, was_redacted = redactor.scrub_payload(original)
    assert was_redacted is True
    assert scrubbed["api_key"] == REDACTED_TOKEN
    assert scrubbed["nested"]["Authorization"] == REDACTED_TOKEN
    assert "[REDACTED_EMAIL]" in scrubbed["nested"]["prompt"]
    assert "[REDACTED_API_KEY]" in scrubbed["nested"]["prompt"]
    assert "[REDACTED_SSN]" in scrubbed["nested"]["prompt"]
    assert scrubbed["nested"]["safe_number"] == 42

    # Caller's original dictionary must remain untouched
    assert original["api_key"] == "plain-secret-value"
    assert "alice.smith@example.com" in original["nested"]["prompt"]


def test_redactor_enforces_max_depth_guard() -> None:
    redactor = EdgeRedactor(max_depth=3)
    deep_payload = {"level1": {"level2": {"level3": {"secret": "value"}}}}
    scrubbed, was_redacted = redactor.scrub_payload(deep_payload)
    assert was_redacted is True
    assert scrubbed["level1"]["level2"]["level3"] == MAX_DEPTH_TOKEN
