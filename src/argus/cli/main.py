"""Command-line interface (CLI) for Argus Control Plane administration."""

from __future__ import annotations

import argparse
import os
import sys
import time

from argus.core.config import ArgusSettings
from argus.core.tenancy import Role, TenantContext
from argus.security.auth import HmacTokenAuthenticator


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level argument parser for the Argus CLI."""
    parser = argparse.ArgumentParser(
        prog="argus",
        description="Argus AgentOps & C2 Control Plane Administration CLI.",
    )
    subparsers = parser.add_subparsers(dest="subcommand", help="Available subcommands")

    # 'auth' command group
    auth_parser = subparsers.add_parser("auth", help="Security and token management")
    auth_subparsers = auth_parser.add_subparsers(dest="auth_action", help="Auth action to perform")

    # 'auth issue-token'
    issue_parser = auth_subparsers.add_parser(
        "issue-token",
        help="Generate a cryptographically signed HMAC-SHA256 Bearer token",
    )
    issue_parser.add_argument(
        "--tenant",
        "-t",
        required=True,
        help="Target tenant identifier (e.g. 'acme-corp')",
    )
    issue_parser.add_argument(
        "--workspace",
        "-w",
        required=True,
        help="Target workspace identifier (e.g. 'prod-eu')",
    )
    issue_parser.add_argument(
        "--actor",
        "-a",
        required=True,
        help="Unique actor or worker identifier (e.g. 'worker-node-1')",
    )
    issue_parser.add_argument(
        "--role",
        "-r",
        choices=[r.value for r in Role],
        default=Role.OPERATOR.value,
        help="RBAC role to grant (VIEWER, INGESTOR, OPERATOR, ADMIN)",
    )
    issue_parser.add_argument(
        "--ttl",
        type=int,
        default=86400,
        help="Token lifetime in seconds (default: 86400 / 24 hours)",
    )
    issue_parser.add_argument(
        "--secret",
        default=None,
        help="Optional custom HMAC secret key (defaults to ARGUS_AUTH_SECRET environment variable)",
    )

    # 'telemetry' command group
    telemetry_parser = subparsers.add_parser("telemetry", help="Telemetry and spool management")
    telemetry_sub = telemetry_parser.add_subparsers(
        dest="telemetry_action", help="Telemetry action"
    )

    # 'telemetry flush-spool'
    flush_parser = telemetry_sub.add_parser(
        "flush-spool", help="Replay locally spooled fail-open spans to Argus"
    )
    flush_parser.add_argument(
        "--tenant", "-t", required=True, help="Target tenant identifier (e.g. 'acme-corp')"
    )
    flush_parser.add_argument(
        "--workspace", "-w", required=True, help="Target workspace identifier (e.g. 'prod-eu')"
    )
    flush_parser.add_argument(
        "--spool-path",
        default=".argus_logs/spool_spans.jsonl",
        help="Path to spool file (default: .argus_logs/spool_spans.jsonl)",
    )
    flush_parser.add_argument(
        "--url", default="http://localhost:8000", help="Argus Control Plane base URL"
    )
    flush_parser.add_argument(
        "--token", default=None, help="Optional Argus HMAC Bearer token"
    )

    # 'serve' command
    serve_parser = subparsers.add_parser("serve", help="Start the Argus C2 Control Plane server")
    serve_parser.add_argument(
        "--host", default="0.0.0.0", help="Bind host address (default: 0.0.0.0)"
    )
    serve_parser.add_argument(
        "--port", "-p", type=int, default=8000, help="Bind port number (default: 8000)"
    )
    serve_parser.add_argument(
        "--reload", action="store_true", help="Enable auto-reload on file changes (development)"
    )
    serve_parser.add_argument(
        "--workers", "-w", type=int, default=1, help="Number of worker processes (default: 1)"
    )

    # 'version' command
    subparsers.add_parser("version", help="Print Argus version information")

    return parser


def handle_issue_token(args: argparse.Namespace) -> int:
    """Execute token generation and print formatted instructions."""
    settings = ArgusSettings.from_env()
    secret = args.secret or settings.auth_secret
    authenticator = HmacTokenAuthenticator(secret_key=secret)

    ctx = TenantContext(
        tenant_id=args.tenant,
        workspace_id=args.workspace,
        actor_id=args.actor,
        role=Role(args.role),
    )

    now_epoch = int(time.time())
    token = authenticator.issue_token(ctx, ttl_seconds=args.ttl, now_epoch=now_epoch)
    expires_at = now_epoch + args.ttl

    sys.stdout.write("\n=== ARGUS CRYPTOGRAPHIC BEARER TOKEN ISSUED ===\n")
    sys.stdout.write(f"Tenant ID:     {ctx.tenant_id}\n")
    sys.stdout.write(f"Workspace ID:  {ctx.workspace_id}\n")
    sys.stdout.write(f"Actor ID:      {ctx.actor_id}\n")
    sys.stdout.write(f"Role:          {ctx.role.value}\n")
    formatted_exp = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(expires_at))
    sys.stdout.write(f"Expires (UTC): {formatted_exp}\n")
    sys.stdout.write("--------------------------------------------------\n")
    sys.stdout.write(f"TOKEN: {token}\n")
    sys.stdout.write("--------------------------------------------------\n")
    sys.stdout.write("Usage in HTTP requests:\n")
    sys.stdout.write(f'  Authorization: Bearer {token}\n\n')
    return 0


def handle_flush_spool(args: argparse.Namespace) -> int:
    """Execute spool replay against the specified Argus endpoint."""
    import asyncio

    from argus.sdk.tracer import ArgusTracer

    ctx = TenantContext(
        tenant_id=args.tenant,
        workspace_id=args.workspace,
        actor_id="cli_spool_replayer",
        role=Role.OPERATOR,
    )
    tracer = ArgusTracer.remote(
        base_url=args.url,
        auth_token=args.token,
        spool_path=args.spool_path,
    )
    count = asyncio.run(tracer.flush_spool(ctx))
    sys.stdout.write(f"Successfully replayed {count} spooled spans to {args.url}\n")
    return 0


def handle_serve(args: argparse.Namespace) -> int:
    """Start the Uvicorn ASGI server for the Argus Control Plane application."""
    import uvicorn

    port = int(os.environ.get("PORT", str(args.port)))
    host = os.environ.get("HOST", args.host)

    sys.stdout.write(f"\n[Argus] Launching Control Plane on http://{host}:{port}\n")
    sys.stdout.write(f"[Argus] Dashboard: http://localhost:{port}/dashboard\n")
    sys.stdout.write(f"[Argus] API Docs:  http://localhost:{port}/docs\n\n")
    uvicorn.run(
        "argus.api.app:app",
        host=host,
        port=port,
        reload=args.reload,
        workers=args.workers if not args.reload else 1,
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI execution entrypoint."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.subcommand == "serve":
        return handle_serve(args)

    if args.subcommand == "auth":
        if args.auth_action == "issue-token":
            return handle_issue_token(args)
        parser.parse_args(["auth", "--help"])
        return 1

    if args.subcommand == "telemetry":
        if args.telemetry_action == "flush-spool":
            return handle_flush_spool(args)
        parser.parse_args(["telemetry", "--help"])
        return 1

    if args.subcommand == "version":
        sys.stdout.write("Argus C2 Control Plane v0.1.0\n")
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
