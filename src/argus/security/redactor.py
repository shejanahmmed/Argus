"""Edge PII and secret redaction engine for telemetry and C2 payloads."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

REDACTED_TOKEN: str = "[REDACTED_BY_ARGUS]"
MAX_DEPTH_TOKEN: str = "[MAX_DEPTH_EXCEEDED]"

# Sensitive dictionary keys are scrubbed regardless of value shape to prevent credential leaks
# in tool arguments, HTTP headers, or LangGraph state snapshots.
_SENSITIVE_KEY_PATTERNS: re.Pattern[str] = re.compile(
    r"(?i)(?:^|_|-)(?:password|passwd|secret|api_?key|access_?token|refresh_?token|"
    r"auth_?token|authorization|private_?key|client_?secret|credit_?card|ssn|cvv)(?:$|_|-)"
)

# Value-level regex patterns ordered from high-specificity credentials to general PII.
_VALUE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # OpenAI / Anthropic / LiteLLM / GitHub / Slack / AWS tokens
    (
        "API_KEY",
        re.compile(
            r"\b(?:sk-(?:proj-|ant-)?[A-Za-z0-9_\-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|"
            r"AKIA[0-9A-Z]{16}|xox[baprs]-[A-Za-z0-9\-]{10,})\b"
        ),
    ),
    # Bearer tokens & standard 3-part base64url JWTs
    (
        "BEARER_OR_JWT",
        re.compile(
            r"(?:Bearer\s+[A-Za-z0-9\-._~+/]+=*|eyJ[A-Za-z0-9_\-]{10,}\."
            r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,})"
        ),
    ),
    # US Social Security Numbers (XXX-XX-XXXX)
    ("SSN", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    # Payment card numbers (13-19 digits with optional spaces or dashes, validated by Luhn check)
    ("EMAIL", re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")),
)

_CANDIDATE_CARD_RE: re.Pattern[str] = re.compile(r"\b(?:\d[ \-]*?){13,19}\b")


def _passes_luhn(digits_only: str) -> bool:
    """Verify candidate payment card strings using Luhn checksum to minimize false positives."""
    if not (13 <= len(digits_only) <= 19) or not digits_only.isdigit():
        return False
    # Reject trivial all-zero strings
    if len(set(digits_only)) == 1 and digits_only[0] == "0":
        return False
    total = 0
    reverse_digits = digits_only[::-1]
    for idx, ch in enumerate(reverse_digits):
        n = int(ch)
        if idx % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


class EdgeRedactor:
    """Stateless, non-mutating recursive PII and credential scrubber for SDK and C2 boundaries."""

    def __init__(
        self,
        *,
        max_depth: int = 16,
        extra_sensitive_keys: set[str] | None = None,
    ) -> None:
        if max_depth < 1:
            raise ValueError("max_depth must be >= 1.")
        self._max_depth = max_depth
        self._extra_keys = {k.lower() for k in (extra_sensitive_keys or set())}

    def is_sensitive_key(self, key: str) -> bool:
        """Return True if a dictionary key matches known credential or PII naming conventions."""
        lowered = key.lower()
        if lowered in self._extra_keys:
            return True
        return bool(_SENSITIVE_KEY_PATTERNS.search(lowered))

    def scrub_string(self, text: str) -> tuple[str, bool]:
        """Scrub credentials and PII inside a string and report whether redaction occurred."""
        redacted = False
        result = text

        for label, pattern in _VALUE_PATTERNS:
            replacement = f"[REDACTED_{label}]"
            new_result, count = pattern.subn(replacement, result)
            if count > 0:
                redacted = True
                result = new_result

        def _replace_card(match: re.Match[str]) -> str:
            nonlocal redacted
            raw = match.group(0)
            digits = re.sub(r"[^\d]", "", raw)
            if _passes_luhn(digits):
                redacted = True
                return "[REDACTED_CREDIT_CARD]"
            return raw

        result = _CANDIDATE_CARD_RE.sub(_replace_card, result)
        return result, redacted

    def scrub_payload(self, payload: Any) -> tuple[Any, bool]:
        """Recursively scrub a payload without mutating the input structure."""
        return self._walk(payload, depth=0)

    def _walk(self, node: Any, *, depth: int) -> tuple[Any, bool]:
        if depth >= self._max_depth:
            return MAX_DEPTH_TOKEN, True

        if isinstance(node, str):
            return self.scrub_string(node)

        if isinstance(node, Mapping):
            out_dict: dict[str, Any] = {}
            any_redacted = False
            for raw_k, v in node.items():
                k_str = str(raw_k)
                if self.is_sensitive_key(k_str):
                    out_dict[k_str] = REDACTED_TOKEN
                    any_redacted = True
                else:
                    cleaned_v, child_redacted = self._walk(v, depth=depth + 1)
                    out_dict[k_str] = cleaned_v
                    any_redacted = any_redacted or child_redacted
            return out_dict, any_redacted

        if isinstance(node, list):
            out_list: list[Any] = []
            any_redacted = False
            for item in node:
                cleaned_item, child_redacted = self._walk(item, depth=depth + 1)
                out_list.append(cleaned_item)
                any_redacted = any_redacted or child_redacted
            return out_list, any_redacted

        if isinstance(node, tuple):
            out_items: list[Any] = []
            any_redacted = False
            for item in node:
                cleaned_item, child_redacted = self._walk(item, depth=depth + 1)
                out_items.append(cleaned_item)
                any_redacted = any_redacted or child_redacted
            return tuple(out_items), any_redacted

        return node, False
