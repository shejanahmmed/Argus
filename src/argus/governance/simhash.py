"""Pure-Python 64-bit SimHash locality-sensitive hashing for near-duplicate cycle detection."""

from __future__ import annotations

import json
import re
from typing import Any

_TOKEN_RE = re.compile(r"(?u)\b\w+\b")
FNV_64_PRIME = 0x100000001B3
FNV_64_INIT = 0xCBF29CE484222325
MASK_64 = 0xFFFFFFFFFFFFFFFF


def fnv1a_64(text: str) -> int:
    """Compute 64-bit FNV-1a hash of a token string."""
    h = FNV_64_INIT
    for byte in text.encode("utf-8"):
        h = ((h ^ byte) * FNV_64_PRIME) & MASK_64
    return h


def extract_features(text_or_payload: str | dict[str, Any] | list[Any]) -> list[str]:
    """Extract word tokens and character 3-grams from text or structured data."""
    if isinstance(text_or_payload, (dict, list)):
        canonical = json.dumps(text_or_payload, sort_keys=True, separators=(",", ":"))
    else:
        canonical = str(text_or_payload)

    words = _TOKEN_RE.findall(canonical.lower())
    features: list[str] = list(words)
    for w in words:
        if len(w) >= 3:
            for j in range(len(w) - 2):
                features.append(w[j : j + 3])
    return features


def compute_simhash64(features: list[str]) -> int:
    """Compute 64-bit SimHash integer fingerprint."""
    if not features:
        return 0
    v = [0] * 64
    for feat in features:
        h = fnv1a_64(feat)
        for i in range(64):
            v[i] += 1 if (h >> i) & 1 else -1
    fingerprint = 0
    for i in range(64):
        if v[i] > 0:
            fingerprint |= 1 << i
    return fingerprint


def payload_simhash(text_or_payload: str | dict[str, Any] | list[Any]) -> int:
    """Convenience helper to extract features and compute 64-bit SimHash in one call."""
    features = extract_features(text_or_payload)
    return compute_simhash64(features)


def hamming_distance64(h1: int, h2: int) -> int:
    """Compute bitwise Hamming distance between two 64-bit fingerprints."""
    return (h1 ^ h2).bit_count()


def simhash_similarity(h1: int, h2: int) -> float:
    """Return normalized similarity [0.0, 1.0] from 64-bit Hamming distance."""
    return round(1.0 - (hamming_distance64(h1, h2) / 64.0), 4)


__all__ = [
    "compute_simhash64",
    "extract_features",
    "fnv1a_64",
    "hamming_distance64",
    "payload_simhash",
    "simhash_similarity",
]
