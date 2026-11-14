"""HMAC-SHA256 Bearer Token Authentication & W3C OpenTelemetry Baggage Parser.

Provides zero-dependency cryptographic bearer token issuance and verification
alongside W3C baggage context extraction (`argus.tenant_id`, `argus.workspace_id`, etc.).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from urllib.parse import unquote

from argus.core.errors import AuthorizationError
from argus.core.tenancy import Role, TenantContext


class HmacTokenAuthenticator:
    """Zero-dependency HMAC-SHA256 signed bearer token issuer and verifier."""

    def __init__(self, secret_key: str | None = None) -> None:
        raw_secret = secret_key or os.environ.get(
            "ARGUS_AUTH_SECRET", "argus-local-dev-hmac-secret-key-2026"
        )
        self._secret = raw_secret.encode("utf-8")

    def issue_token(
        self,
        ctx: TenantContext,
        *,
        ttl_seconds: int = 3600,
        now_epoch: int | None = None,
    ) -> str:
        """Issue a signed HMAC-SHA256 bearer token for a TenantContext."""
        issued_at = now_epoch if now_epoch is not None else int(time.time())
        claims = {
            "tenant_id": ctx.tenant_id,
            "workspace_id": ctx.workspace_id,
            "actor_id": ctx.actor_id,
            "role": ctx.role.value,
            "iat": issued_at,
            "exp": issued_at + max(1, ttl_seconds),
        }
        payload_bytes = json.dumps(claims, separators=(",", ":"), sort_keys=True).encode("utf-8")
        payload_b64 = base64.urlsafe_b64encode(payload_bytes).decode("ascii").rstrip("=")
        signature = hmac.new(self._secret, payload_b64.encode("ascii"), hashlib.sha256).hexdigest()
        return f"argus_tok.{payload_b64}.{signature}"

    def verify_token(
        self,
        token: str,
        *,
        now_epoch: int | None = None,
    ) -> TenantContext:
        """Verify an HMAC-SHA256 bearer token and return the decoded TenantContext."""
        parts = token.strip().split(".")
        if len(parts) != 3 or parts[0] != "argus_tok":
            raise AuthorizationError("Malformed Argus bearer token.")

        _, payload_b64, provided_sig = parts
        expected_sig = hmac.new(
            self._secret, payload_b64.encode("ascii"), hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(expected_sig, provided_sig):
            raise AuthorizationError("Invalid bearer token cryptographic signature.")

        padding = "=" * (-len(payload_b64) % 4)
        try:
            decoded_bytes = base64.urlsafe_b64decode(payload_b64 + padding)
            claims = json.loads(decoded_bytes.decode("utf-8"))
        except Exception as err:
            raise AuthorizationError("Corrupted bearer token payload.") from err

        current_epoch = now_epoch if now_epoch is not None else int(time.time())
        exp = int(claims.get("exp", 0))
        if current_epoch >= exp:
            raise AuthorizationError("Bearer token has expired.")

        try:
            role_val = Role(str(claims["role"]).upper())
            return TenantContext(
                tenant_id=str(claims["tenant_id"]),
                workspace_id=str(claims["workspace_id"]),
                actor_id=str(claims["actor_id"]),
                role=role_val,
            )
        except Exception as err:
            raise AuthorizationError(f"Invalid tenant claims in bearer token: {err}") from err


def parse_w3c_baggage(baggage_header: str | None) -> dict[str, str]:
    """Parse W3C OpenTelemetry baggage header into a key-value dictionary.

    Example header:
        "argus.tenant_id=acme,argus.workspace_id=prod;prop=1,argus.role=OPERATOR"
    """
    if not baggage_header:
        return {}

    extracted: dict[str, str] = {}
    for member in baggage_header.split(","):
        # Strip optional W3C baggage properties (;prop=val)
        kv_segment = member.split(";", 1)[0].strip()
        if "=" not in kv_segment:
            continue
        raw_key, raw_val = kv_segment.split("=", 1)
        key = unquote(raw_key.strip())
        val = unquote(raw_val.strip())
        if key and val:
            extracted[key] = val
    return extracted
