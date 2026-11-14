# ARGUS — Autonomous Agent Governance, Observability & C2 Control Plane

**Argus** is an enterprise-grade **AgentOps Governance, Telemetry, and Command & Control (C2) Control Plane** engineered to monitor, intercept, evaluate, and govern autonomous AI agents (LangGraph, LCEL, CrewAI, AutoGPT, and Model Context Protocol [MCP] tool runtimes) at scale with zero tolerance for runaway loops, budget depletion, or unauthorized tool execution.

---

## System Architecture

```mermaid
flowchart TB
    subgraph Runtimes["Autonomous Agent Runtimes"]
        LG["LangGraph / LCEL"]
        CA["CrewAI / AutoGPT"]
        MCP["MCP Tool Clients"]
    end

    subgraph SDK["Argus Edge SDK & MCP Shield"]
        TRACER["ArgusTracer (UUIDv7, dotted_order, Edge PII Redactor, Fail-Open Spool)"]
        C2_SDK["ArgusC2Client (Checkpoints, Heartbeats, Pre-Execution Gate)"]
    end

    subgraph ControlPlane["Argus FastAPI Control Plane"]
        AUTH["AuthZ & Tenant Isolation (HMAC Bearer Token, RBAC, W3C Baggage)"]
        INGEST["OTel GenAI, OpenInference & CloudWatch Log Ingestors"]
        CB["3-Tier Loop Detector & Atomic Budget Enforcer"]
        MCP_PROXY["MCP Governance Proxy (ABAC tools/list + Destructive tools/call Gate)"]
        C2_ENGINE["Distributed C2 Engine (RFC 6902 Patch, SHA-256 Override, Dead-Man Switch)"]
        ROI["Financial ROI Attribution, Trajectory Evaluator & HF Pareto Analyzer"]
        WS["Real-Time WebSocket EventBus (/ws/v1/stream)"]
    end

    subgraph Storage["Hexagonal Persistence Layer ($0 Self-Hosted OSS)"]
        MEM_SQL["In-Memory / WAL-Mode SQLite / PostgreSQL 16 + ClickHouse 24 + Valkey 7"]
    end

    subgraph Dashboard["Stark #000000 Monochrome C2 Console (React 19 + TypeScript + React Flow)"]
        UI_DAG["Live LangGraph Cyclic Topology & Token Velocity"]
        UI_C2["HITL Tool Override Interceptor & RFC 6902 State Editor"]
        UI_ROI["Workflow ROI Ledger, Pareto Matrix & Container Log Waterfall"]
    end

    LG & CA & MCP --> TRACER & C2_SDK
    TRACER & C2_SDK --> AUTH
    AUTH --> INGEST & MCP_PROXY & C2_ENGINE & ROI
    INGEST --> CB
    INGEST & CB & MCP_PROXY & C2_ENGINE & ROI <--> MEM_SQL
    INGEST & CB & MCP_PROXY & C2_ENGINE --> WS <--> UI_DAG & UI_C2 & UI_ROI
```

---

## Core Engineering Capabilities

### 1. Cross-Platform Telemetry SDK & OpenTelemetry / OpenInference Pipeline
- **Chronological `UUIDv7` & `dotted_order` Hierarchy**: Every span carries a RFC 9562 `UUIDv7` identifier and a lexicographically sortable `dotted_order` path (`<timestamp>Z<uuid>.<child_timestamp>Z<child_uuid>`), enabling $O(1)$ prefix subtree reconstruction without recursive SQL CTEs.
- **Dual Semantic Conventions**: Normalizes traces across **OpenTelemetry GenAI (`gen_ai.*`)** and **Arize Phoenix OpenInference (`openinference.span.kind`)** simultaneously.
- **Framework Instrumentors**: Built-in non-invasive adapters for **LangGraph**, **LCEL**, **CrewAI**, and **AutoGPT**, plus an `@tracer.trace(...)` decorator.
- **Edge PII & Secret Scrubbing**: Deterministic regex + Shannon entropy redaction strips API keys, bearer tokens, AWS credentials, SSNs, and emails *before* spans leave the worker process.
- **Fail-Open Local Spooling**: If telemetry storage is unreachable, spans automatically spool to `.argus_logs/spool_spans.jsonl` so observability outages never crash customer agents.

### 2. 3-Tier Automated Loop Circuit Breaker & Atomic Budget Guard
Argus evaluates every reasoning step and tool invocation in `< 2 ms` across three detection tiers:
1. **Tier 1 — Exact Signature Hash ($O(1)$)**: Canonical JSON SHA-256 digest of `(tool_name, tool_args)` catches identical repeated tool calls immediately.
2. **Tier 2 — Structural Cycle & SimHash Detection ($O(W)$)**: Detects `A -> B -> A -> B` state oscillations and 64-bit SimHash Hamming distance near-duplicates across a sliding window.
3. **Tier 3 — Cosine Semantic Stagnation**: Computes character $n$-gram TF-IDF cosine similarity $\cos(\vec{v}_t, \vec{v}_{t-1}) \ge 0.90$ across consecutive reasoning steps to halt paraphrased infinite loops.
4. **Pre-Execution Hard Budget Enforcer**: Atomically reserves token and tool spend against tenant/session USD caps, tripping to `TRIPPED_BUDGET` (`HTTP 402 Payment Required`) before upstream LLM calls execute.

### 3. Model Context Protocol (MCP) Governance Proxy
- **`tools/list` RBAC/ABAC Filtering**: Dynamically filters available MCP tools based on the caller's `TenantContext` role (`VIEWER`, `OPERATOR`, `ADMIN`).
- **`tools/call` Pre-Execution Gate & Prompt-Injection Shield**: Scans tool arguments for prompt-injection and command-injection payloads, enforces budget/loop checks, and automatically transitions high-risk/destructive tool calls (`drop_*`, `delete_*`, `exec_*`, `transfer_*`) into `PAUSED_C2` for human authorization.

### 4. Distributed Command & Control (C2) Plane
- **Optimistic Concurrency Memory Patching (RFC 6902)**: Operators inspect and mutate agent memory mid-execution via RFC 6902 JSON Patch operations (`add`, `replace`, `remove`) guarded by `expected_parent_checkpoint_id` (`HTTP 409 Conflict` on stale writes).
- **Cryptographic Tool Override Engine**: Operators can `approve`, `edit` arguments, `mock` output, or `reject` intercepted tool calls, bound by a SHA-256 request digest (`request_digest_sha256`) to prevent TOCTOU tampering.
- **Worker Heartbeats & Dead-Man's Switch**: Distributed workers renew time-bounded leases via `POST /api/v1/c2/{session_id}/heartbeat`; orphaned sessions are automatically reaped (`POST /api/v1/c2/leases/reap`) to `TERMINATED` (`ABORT_SAFE`).
- **Tamper-Evident SHA-256 Audit Ledger**: Every operator intervention and circuit-breaker trip is recorded in a hash-chained SHA-256 compliance ledger verified via `GET /api/v1/c2/{session_id}/audit-log`.

### 5. Financial ROI Attribution & Hugging Face Pareto Efficiency Matrix
- Computes exact **Net Workflow ROI**:
  $$\text{Net ROI (USD)} = (\text{Task Completion} \times \text{Assigned Business Value}) - (\text{LLM Cost} + \text{Tool Cost} + \text{Infra Cost} + \text{Wasted Loop Cost})$$
- Benchmarks active models against **Hugging Face Open LLM / GAIA Leaderboard** profiles to recommend Pareto-optimal open-weight model substitutions (e.g., Qwen-2.5-72B, Llama-3.3-70B, DeepSeek-V3) that preserve accuracy while cutting latency and token spend.

---

## Quickstart

### 1. Backend Setup & Verification
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"

# Run the full 60+ test suite, strict Mypy type checker, and Ruff linter
pytest -v
mypy --strict src tests
ruff check src tests
```

### 2. Launch Control Plane & Stark `#000000` Monochrome Dashboard
```powershell
# Terminal 1: Start the FastAPI Control Plane (supports ARGUS_STORAGE_BACKEND=memory or sqlite)
uvicorn argus.api.app:app --reload --port 8000

# Terminal 2: Start the React 19 + TypeScript + Vite C2 Console
cd dashboard
npm install
npm run dev
```

Open `http://localhost:5173` and click **SEED DEMO SCENARIO** in the top command bar to populate multi-agent LangGraph, CrewAI, and AutoGPT traces, trigger a live recursive loop trip, inspect a paused destructive MCP tool call, apply an RFC 6902 memory patch, and verify the SHA-256 audit chain.

### 3. Optional Self-Hosted Docker Infrastructure
```powershell
docker compose up -d
```
Provisions local **PostgreSQL 16**, **ClickHouse 24**, and **Valkey 7** (`$0` self-hosted open-source stack).
