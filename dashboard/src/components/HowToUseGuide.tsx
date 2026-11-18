import React, { useState } from "react";
import {
  Play,
  ShieldCheck,
  GitBranch,
  SlidersHorizontal,
  CircleDollarSign,
  Copy,
  Check,
  Terminal,
  ArrowRight,
  ExternalLink,
  BookOpen,
  Sparkles,
} from "lucide-react";
import { ArgusLogo } from "./ArgusLogo";
import { ViewMode } from "../types";

interface HowToUseGuideProps {
  onSeedScenario: () => void;
  onSelectView: (view: ViewMode) => void;
  seeding: boolean;
  hasSessions: boolean;
}

export const HowToUseGuide: React.FC<HowToUseGuideProps> = ({
  onSeedScenario,
  onSelectView,
  seeding,
  hasSessions,
}) => {
  const [copiedSdk, setCopiedSdk] = useState<boolean>(false);

  const sdkCode = `from argus.sdk.tracer import ArgusTracer
from argus.core.tenancy import TenantContext, Role

# 1. Initialize client security & tenancy context
ctx = TenantContext(
    tenant_id="acme_corp",
    workspace_id="production",
    actor_id="agent_alpha",
    role=Role.OPERATOR
)
tracer = ArgusTracer.remote(base_url="http://localhost:8000")

# 2. Decorate any autonomous agent reasoning step
@tracer.trace(name="plan_and_execute", span_kind="agent")
async def run_agent(prompt: str) -> str:
    # Argus evaluates loops, enforces token budgets,
    # and intercepts dangerous tools inline (<2ms)
    return "Task completed"`;

  const handleCopyCode = () => {
    navigator.clipboard.writeText(sdkCode);
    setCopiedSdk(true);
    setTimeout(() => setCopiedSdk(false), 2000);
  };

  const handleLaunchAndExplore = () => {
    onSeedScenario();
    onSelectView("ALL");
  };

  return (
    <div className="max-w-7xl mx-auto w-full flex flex-col gap-8 pb-12 animate-in fade-in duration-300 select-none">
      {/* Hero Header */}
      <div className="rounded-xl border border-[#222228] bg-[#0c0c0f] p-6 sm:p-8 relative overflow-hidden shadow-2xl">
        <div className="absolute top-0 right-0 p-8 opacity-5 pointer-events-none">
          <ArgusLogo className="h-64 w-64 text-emerald-400" />
        </div>

        <div className="relative z-10 flex flex-col gap-4 max-w-3xl">
          <div className="flex items-center gap-2">
            <span className="flex h-2 w-2 rounded-full bg-emerald-400" />
            <span className="text-[11px] font-mono tracking-wider text-emerald-400 uppercase font-semibold">
              OPERATOR ONBOARDING & ARCHITECTURE RUNBOOK
            </span>
            <span className="text-zinc-600 text-xs">•</span>
            <span
              className={`text-[10px] font-mono px-2 py-0.5 rounded border ${
                hasSessions
                  ? "border-emerald-500/30 bg-emerald-950/20 text-emerald-400"
                  : "border-zinc-700/50 bg-zinc-900/50 text-zinc-400"
              }`}
            >
              {hasSessions ? "FLEET ACTIVE" : "AWAITING SCENARIOS"}
            </span>
          </div>

          <h1 className="text-2xl sm:text-3xl font-bold tracking-tight text-white font-sans">
            How to Operate the Argus Control Plane
          </h1>

          <p className="text-zinc-400 text-sm leading-relaxed font-sans">
            Argus is a zero-tolerance AgentOps governance, observability, and Command & Control
            (C2) control plane. Unlike passive log collectors, Argus operates as an{" "}
            <span className="text-zinc-200 font-medium">active inline supervisor</span> with sub-2ms
            decision latency—intercepting destructive actions, halting infinite loops, and hot-patching
            agent memory in real time.
          </p>

          <div className="flex flex-wrap items-center gap-3 pt-2">
            <button
              onClick={handleLaunchAndExplore}
              disabled={seeding}
              className="flex items-center gap-2 rounded-md bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 px-4 py-2 text-xs font-semibold text-white shadow-lg transition-all cursor-pointer font-sans"
            >
              <Play className="h-3.5 w-3.5 fill-current" />
              <span>{seeding ? "Seeding Scenario..." : "Seed 3 Live Scenarios & Explore"}</span>
            </button>

            <button
              onClick={() => onSelectView("TOPOLOGY")}
              className="flex items-center gap-2 rounded-md border border-[#2a2a34] bg-[#141418] hover:bg-[#1c1c24] px-4 py-2 text-xs font-medium text-zinc-200 transition-colors cursor-pointer font-sans"
            >
              <GitBranch className="h-3.5 w-3.5 text-zinc-400" />
              <span>Topology Visualizer</span>
            </button>

            <button
              onClick={() => onSelectView("C2_LAB")}
              className="flex items-center gap-2 rounded-md border border-[#2a2a34] bg-[#141418] hover:bg-[#1c1c24] px-4 py-2 text-xs font-medium text-zinc-200 transition-colors cursor-pointer font-sans"
            >
              <SlidersHorizontal className="h-3.5 w-3.5 text-zinc-400" />
              <span>C2 Governance Lab</span>
            </button>

            <button
              onClick={() => {
                sessionStorage.removeItem("argus_boot_shown");
                window.location.reload();
              }}
              className="flex items-center gap-2 rounded-md border border-[#2a2a34] bg-[#141418] hover:bg-[#1c1c24] px-4 py-2 text-xs font-medium text-zinc-300 transition-colors cursor-pointer font-sans"
              title="Replay the high-speed system initialization sequence"
            >
              <Sparkles className="h-3.5 w-3.5 text-emerald-400" />
              <span>Replay Intro</span>
            </button>
          </div>
        </div>
      </div>

      {/* 4 Core Pillars Grid */}
      <div className="flex flex-col gap-3">
        <div className="flex items-center justify-between border-b border-[#222228] pb-2">
          <div className="flex items-center gap-2">
            <BookOpen className="h-4 w-4 text-emerald-400" />
            <h2 className="text-xs font-mono font-bold uppercase tracking-wider text-zinc-200">
              The 4 Core Architectural Capabilities
            </h2>
          </div>
          <span className="text-[11px] font-mono text-zinc-500">Sub-2ms Inline Telemetry</span>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {/* Pillar 1: Loop Breaker */}
          <div className="rounded-lg border border-[#222228] bg-[#121215] p-5 flex flex-col justify-between gap-4 hover:border-zinc-700 transition-all">
            <div className="flex flex-col gap-2.5">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <div className="p-1.5 rounded bg-rose-950/40 border border-rose-500/30 text-rose-400">
                    <GitBranch className="h-4 w-4" />
                  </div>
                  <span className="font-semibold text-sm text-zinc-100 font-sans">
                    1. 3-Tier Cyclic Loop Breaking
                  </span>
                </div>
                <span className="px-2 py-0.5 rounded text-[10px] font-mono font-semibold bg-rose-950/40 border border-rose-500/30 text-rose-300">
                  TRIPPED_LOOP
                </span>
              </div>
              <p className="text-xs text-zinc-400 leading-relaxed font-sans">
                Autonomous agents frequently get trapped in non-deterministic repeating loops. Argus
                evaluates execution graphs against three mathematical tiers:
              </p>
              <ul className="text-[11px] text-zinc-400 font-mono space-y-1 list-disc list-inside">
                <li><span className="text-zinc-200">Exact Repetition:</span> Sliding-window SHA-256 state hashing.</li>
                <li><span className="text-zinc-200">Oscillating Flips:</span> 64-bit SimHash Hamming distance.</li>
                <li><span className="text-zinc-200">Semantic Stagnation:</span> Character 3-gram cosine similarity.</li>
              </ul>
            </div>
            <div className="pt-2 border-t border-[#1f1f24] flex items-center justify-between text-[11px]">
              <span className="text-zinc-500 font-mono">Status: Halts before budget burns</span>
              <button
                onClick={() => onSelectView("TOPOLOGY")}
                className="text-emerald-400 hover:text-emerald-300 font-medium flex items-center gap-1 cursor-pointer"
              >
                Inspect on DAG <ArrowRight className="h-3 w-3" />
              </button>
            </div>
          </div>

          {/* Pillar 2: Pre-Execution MCP Governance */}
          <div className="rounded-lg border border-[#222228] bg-[#121215] p-5 flex flex-col justify-between gap-4 hover:border-zinc-700 transition-all">
            <div className="flex flex-col gap-2.5">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <div className="p-1.5 rounded bg-amber-950/40 border border-amber-500/30 text-amber-400">
                    <ShieldCheck className="h-4 w-4" />
                  </div>
                  <span className="font-semibold text-sm text-zinc-100 font-sans">
                    2. Pre-Execution MCP Proxy
                  </span>
                </div>
                <span className="px-2 py-0.5 rounded text-[10px] font-mono font-semibold bg-amber-950/40 border border-amber-500/30 text-amber-300">
                  PAUSED_C2
                </span>
              </div>
              <p className="text-xs text-zinc-400 leading-relaxed font-sans">
                Agents with tool-calling capabilities can execute destructive commands. Argus intercepts
                Model Context Protocol (MCP) JSON-RPC calls before dispatch:
              </p>
              <ul className="text-[11px] text-zinc-400 font-mono space-y-1 list-disc list-inside">
                <li><span className="text-zinc-200">Risk Interception:</span> Catches drops, deletes, and transfers.</li>
                <li><span className="text-zinc-200">Operator Decision:</span> Approve, Edit parameters, or Reject.</li>
                <li><span className="text-zinc-200">Mocking Sandbox:</span> Return test payloads safely.</li>
              </ul>
            </div>
            <div className="pt-2 border-t border-[#1f1f24] flex items-center justify-between text-[11px]">
              <span className="text-zinc-500 font-mono">Bound by SHA-256 TOCTOU digest</span>
              <button
                onClick={() => onSelectView("C2_LAB")}
                className="text-amber-400 hover:text-amber-300 font-medium flex items-center gap-1 cursor-pointer"
              >
                Open C2 Lab <ArrowRight className="h-3 w-3" />
              </button>
            </div>
          </div>

          {/* Pillar 3: Memory Hot-Patching */}
          <div className="rounded-lg border border-[#222228] bg-[#121215] p-5 flex flex-col justify-between gap-4 hover:border-zinc-700 transition-all">
            <div className="flex flex-col gap-2.5">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <div className="p-1.5 rounded bg-blue-950/40 border border-blue-500/30 text-blue-400">
                    <SlidersHorizontal className="h-4 w-4" />
                  </div>
                  <span className="font-semibold text-sm text-zinc-100 font-sans">
                    3. Memory Hot-Patching (RFC 6902)
                  </span>
                </div>
                <span className="px-2 py-0.5 rounded text-[10px] font-mono font-semibold bg-blue-950/40 border border-blue-500/30 text-blue-300">
                  IN-FLIGHT PATCH
                </span>
              </div>
              <p className="text-xs text-zinc-400 leading-relaxed font-sans">
                When an agent hallucinates a corrupted variable, you do not have to abort the session.
                Argus enables mid-flight working memory modification:
              </p>
              <ul className="text-[11px] text-zinc-400 font-mono space-y-1 list-disc list-inside">
                <li><span className="text-zinc-200">RFC 6902 JSON Patch:</span> Atomic add, replace, and remove.</li>
                <li><span className="text-zinc-200">Checkpoint Guard:</span> Parent checkpoint ID validation eliminates race conditions.</li>
                <li><span className="text-zinc-200">Zero Termination:</span> Fix the agent and resume immediately.</li>
              </ul>
            </div>
            <div className="pt-2 border-t border-[#1f1f24] flex items-center justify-between text-[11px]">
              <span className="text-zinc-500 font-mono">Optimistic Concurrency Control</span>
              <button
                onClick={() => onSelectView("C2_LAB")}
                className="text-blue-400 hover:text-blue-300 font-medium flex items-center gap-1 cursor-pointer"
              >
                Inspect State Diff <ArrowRight className="h-3 w-3" />
              </button>
            </div>
          </div>

          {/* Pillar 4: FinOps Attribution */}
          <div className="rounded-lg border border-[#222228] bg-[#121215] p-5 flex flex-col justify-between gap-4 hover:border-zinc-700 transition-all">
            <div className="flex flex-col gap-2.5">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <div className="p-1.5 rounded bg-emerald-950/40 border border-emerald-500/30 text-emerald-400">
                    <CircleDollarSign className="h-4 w-4" />
                  </div>
                  <span className="font-semibold text-sm text-zinc-100 font-sans">
                    4. FinOps ROI & GAIA Swaps
                  </span>
                </div>
                <span className="px-2 py-0.5 rounded text-[10px] font-mono font-semibold bg-emerald-950/40 border border-emerald-500/30 text-emerald-300">
                  PARETO OPTIMAL
                </span>
              </div>
              <p className="text-xs text-zinc-400 leading-relaxed font-sans">
                Track exact net yield by mapping token consumption (prompt, completion, cache) and
                compute runtime against verified task value:
              </p>
              <ul className="text-[11px] text-zinc-400 font-mono space-y-1 list-disc list-inside">
                <li><span className="text-zinc-200">4-Tier Allocation:</span> LLM spend, tool fees, container compute.</li>
                <li><span className="text-zinc-200">Hugging Face GAIA:</span> Benchmarks accuracy vs unit cost.</li>
                <li><span className="text-zinc-200">Open-Weight Downgrades:</span> Recommends Llama 3.3 or Qwen 2.5 to save 80%+.</li>
              </ul>
            </div>
            <div className="pt-2 border-t border-[#1f1f24] flex items-center justify-between text-[11px]">
              <span className="text-zinc-500 font-mono">Net Yield = Business Value - Cost</span>
              <button
                onClick={() => onSelectView("FINOPS")}
                className="text-emerald-400 hover:text-emerald-300 font-medium flex items-center gap-1 cursor-pointer"
              >
                View FinOps Matrix <ArrowRight className="h-3 w-3" />
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* 3-Line Python SDK Integration */}
      <div className="rounded-xl border border-[#222228] bg-[#0d0d10] p-6 flex flex-col gap-4">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[#1f1f24] pb-3">
          <div className="flex items-center gap-2">
            <Terminal className="h-4 w-4 text-emerald-400" />
            <h3 className="text-xs font-mono font-bold uppercase tracking-wider text-zinc-200">
              Connect Any Agent Runtime in 3 Lines of Python
            </h3>
          </div>
          <button
            onClick={handleCopyCode}
            className="flex items-center gap-1.5 px-3 py-1 rounded bg-[#18181e] hover:bg-[#22222a] border border-[#2a2a34] text-xs font-mono text-zinc-300 transition-colors cursor-pointer"
          >
            {copiedSdk ? (
              <>
                <Check className="h-3.5 w-3.5 text-emerald-400" />
                <span className="text-emerald-400">Copied!</span>
              </>
            ) : (
              <>
                <Copy className="h-3.5 w-3.5 text-zinc-400" />
                <span>Copy SDK Code</span>
              </>
            )}
          </button>
        </div>

        <pre className="p-4 rounded-lg bg-[#070709] border border-[#1b1b22] text-xs font-mono text-zinc-300 overflow-x-auto leading-relaxed">
          <code>{sdkCode}</code>
        </pre>

        <p className="text-[11px] text-zinc-500 font-mono leading-relaxed">
          * Argus SDK automatically serializes state checkpoints, captures OpenTelemetry GenAI spans,
          and spools asynchronously with fail-open fallback so your production agent never crashes on
          network degradation.
        </p>
      </div>

      {/* Operator Cheat Sheet & Hotkeys */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="rounded-lg border border-[#222228] bg-[#121215] p-4 flex flex-col gap-2">
          <span className="text-xs font-mono font-bold text-zinc-300 uppercase tracking-wide">
            Interactive Views
          </span>
          <div className="text-[11px] text-zinc-400 font-sans space-y-2">
            <div>
              <span className="font-semibold text-zinc-200 font-mono">Overview:</span> Consolidated
              dashboard deck featuring fleet health, live DAG, and C2 lab.
            </div>
            <div>
              <span className="font-semibold text-zinc-200 font-mono">Topology:</span> Fullscreen
              interactive React Flow execution graph with animated cycle edges.
            </div>
            <div>
              <span className="font-semibold text-zinc-200 font-mono">C2 Governance:</span> Deep-dive
              into pending tool approvals and SHA-256 compliance ledger.
            </div>
          </div>
        </div>

        <div className="rounded-lg border border-[#222228] bg-[#121215] p-4 flex flex-col gap-2">
          <span className="text-xs font-mono font-bold text-zinc-300 uppercase tracking-wide">
            Simulation Toolkit
          </span>
          <div className="text-[11px] text-zinc-400 font-sans space-y-2">
            <div>
              <span className="font-semibold text-zinc-200 font-mono">Seed Scenario:</span> Creates
              LangGraph loop, CrewAI tool pause, and AutoGPT cost traces.
            </div>
            <div>
              <span className="font-semibold text-zinc-200 font-mono">Simulate Loop:</span> Injects an
              extra cyclic iteration into the active session.
            </div>
            <div>
              <span className="font-semibold text-zinc-200 font-mono">Simulate Attack:</span> Emits a
              malicious drop_database tool call to verify pre-execution interception.
            </div>
          </div>
        </div>

        <div className="rounded-lg border border-[#222228] bg-[#121215] p-4 flex flex-col gap-2">
          <span className="text-xs font-mono font-bold text-zinc-300 uppercase tracking-wide">
            Enterprise Endpoints
          </span>
          <div className="text-[11px] text-zinc-400 font-sans space-y-2">
            <div>
              <a
                href="/docs"
                target="_blank"
                rel="noreferrer"
                className="text-emerald-400 hover:underline font-mono inline-flex items-center gap-1"
              >
                /docs <ExternalLink className="h-2.5 w-2.5" />
              </a>
              : Interactive FastAPI Swagger OpenAPI documentation.
            </div>
            <div>
              <a
                href="/metrics"
                target="_blank"
                rel="noreferrer"
                className="text-emerald-400 hover:underline font-mono inline-flex items-center gap-1"
              >
                /metrics <ExternalLink className="h-2.5 w-2.5" />
              </a>
              : Prometheus scrape endpoint for Grafana dashboards.
            </div>
            <div>
              <a
                href="/readyz"
                target="_blank"
                rel="noreferrer"
                className="text-emerald-400 hover:underline font-mono inline-flex items-center gap-1"
              >
                /readyz <ExternalLink className="h-2.5 w-2.5" />
              </a>
              : Storage engine integrity & WAL diagnostic probe.
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
