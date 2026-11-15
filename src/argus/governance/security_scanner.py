"""Zero-spend security scanner for shell-injection and prompt-injection defense in MCP tools."""

from __future__ import annotations

import re
from typing import Any

_SHELL_INJECTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"(?i)(?:;|&&|\|)\s*(?:rm\s+-rf|rmdir|mkfs|dd|chmod|chown|kill|reboot|shutdown"
        r"|bash|sh|zsh|dash|powershell|pwsh|cmd(?:\.exe)?)"
    ),
    re.compile(r"(?i)(?:;|&&|\|)\s*(?:curl|wget)\s+.*\|\s*(?:bash|sh|python|perl)"),
    re.compile(r"(?i)`[^`]+`"),
    re.compile(r"(?i)\$\([^)]+\)"),
    re.compile(r"(?i)(?:/etc/passwd|/etc/shadow|/proc/version|c:\\windows\\system32|windows/system32|\.\./\.\./)"),
    re.compile(r"(?i)powershell(?:\.exe)?\s+(?:-[a-z]+\s+)*-(?:enc|encodedcommand)"),
    re.compile(r"(?i)nc\s+(?:-[a-z]+\s+)*-e\s+"),
)

_PROMPT_INJECTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)ignore\s+(?:all\s+)?(?:previous|prior)\s+(?:instructions|directives|prompts)"),
    re.compile(r"(?i)disregard\s+(?:all\s+)?(?:previous|prior)\s+(?:instructions|rules)"),
    re.compile(r"(?i)system\s+(?:prompt\s+)?override(?:\s*:|$)"),
    re.compile(
        r"(?i)(?:do\s+not|never|don't)\s+follow\s+(?:any\s+)?(?:safety|system|security)\s+(?:guidelines|rules|instructions)"
    ),
    re.compile(
        r"(?i)bypass\s+(?:all\s+)?(?:circuit\s+breakers|budget\s+checks|safety|security|safeguards)"
    ),
    re.compile(r"(?i)you\s+are\s+now\s+(?:in\s+developer\s+mode|unfiltered|dan|jailbroken)"),
    re.compile(r"(?i)<\s*(?:system|system_prompt)\s*>"),
)

REDACTION_MARKER = "[REDACTED_BY_ARGUS_SECURITY]"


def scan_for_shell_injection(text: str) -> str | None:
    """Detect shell command injection, command substitution, or unauthorized system paths."""
    for pattern in _SHELL_INJECTION_PATTERNS:
        match = pattern.search(text)
        if match:
            return f"Shell injection pattern detected: '{match.group(0).strip()}'"
    return None


def scan_for_prompt_injection(text: str) -> str | None:
    """Detect prompt injection, system prompt override, or jailbreak patterns."""
    for pattern in _PROMPT_INJECTION_PATTERNS:
        match = pattern.search(text)
        if match:
            return f"Prompt injection pattern detected: '{match.group(0).strip()}'"
    return None


def sanitize_tool_description(description: str) -> str:
    """Sanitize MCP tool descriptions by redacting prompt-injection jailbreak phrases."""
    sanitized = description
    for pattern in _PROMPT_INJECTION_PATTERNS:
        sanitized = pattern.sub(REDACTION_MARKER, sanitized)
    return sanitized


def scan_tool_arguments(payload: Any) -> tuple[bool, str | None]:
    """Recursively evaluate tool arguments against shell-injection and prompt-injection patterns."""
    if isinstance(payload, str):
        shell_threat = scan_for_shell_injection(payload)
        if shell_threat:
            return True, shell_threat
        prompt_threat = scan_for_prompt_injection(payload)
        if prompt_threat:
            return True, prompt_threat
        return False, None

    if isinstance(payload, dict):
        for key, val in payload.items():
            key_threat = scan_for_shell_injection(str(key))
            if key_threat:
                return True, f"Malicious parameter key: {key_threat}"
            tripped, threat = scan_tool_arguments(val)
            if tripped:
                return True, threat
        return False, None

    if isinstance(payload, list):
        for item in payload:
            tripped, threat = scan_tool_arguments(item)
            if tripped:
                return True, threat
        return False, None

    return False, None


__all__ = [
    "REDACTION_MARKER",
    "sanitize_tool_description",
    "scan_for_prompt_injection",
    "scan_for_shell_injection",
    "scan_tool_arguments",
]
