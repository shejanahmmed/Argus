import React from "react";
import {
  Database,
  ShieldCheck,
  Activity,
  Download,
  CheckCircle2,
  Lock,
  Cpu,
  BookOpen,
  Sparkles,
  FileCode,
} from "lucide-react";
import { ArgusLogo } from "./ArgusLogo";
import { AgentSession, StorageDiagnostics, ViewMode } from "../types";

export interface FooterProps {
  wsConnected: boolean;
  sessions: AgentSession[];
  selectedSessionId: string | null;
  tenantId: string;
  workspaceId: string;
  storageBackend?: string;
  storageDiagnostics?: StorageDiagnostics | null;
  systemReady?: boolean;
  onExportAuditLog?: (sessionId: string) => void;
  onSelectView?: (view: ViewMode) => void;
}

export const Footer: React.FC<FooterProps> = ({
  wsConnected,
  sessions,
  selectedSessionId,
  tenantId,
  workspaceId,
  storageBackend = "sqlite",
  storageDiagnostics,
  systemReady = true,
  onExportAuditLog,
  onSelectView,
}) => {
  const activeCount = sessions.filter((s) => s.status === "RUNNING").length;
  const pausedCount = sessions.filter((s) => s.status === "PAUSED_C2").length;
  const trippedCount = sessions.filter(
    (s) => s.status === "TRIPPED_LOOP" || s.status === "TRIPPED_BUDGET"
  ).length;
  const totalCost = sessions.reduce((acc, s) => acc + s.accumulated_cost_usd, 0);

  const handleExportClick = () => {
    if (!selectedSessionId) return;
    if (onExportAuditLog) {
      onExportAuditLog(selectedSessionId);
    } else {
      window.open(`/api/v1/c2/${selectedSessionId}/audit-log/export?format=json`, "_blank");
    }
  };

  return (
    <footer className="border-t border-[#1f1f24] bg-[#09090b]/95 backdrop-blur-md px-4 sm:px-6 py-3 font-mono text-[11px] text-zinc-400 select-none">
      {/* Primary Status Grid / Responsive Flex Layout */}
      <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-3 lg:gap-6">
        {/* Left Sector: Engine Heartbeat, Persistence, and Multi-Tenant Identity */}
        <div className="flex flex-wrap items-center gap-2 sm:gap-3 text-zinc-400">
          {/* Brand Mark with Monogram */}
          <div className="flex items-center gap-1.5 pr-1 border-r border-[#222228]">
            <ArgusLogo className="h-3.5 w-3.5 text-emerald-400 shrink-0" />
            <span className="font-sans font-bold tracking-wider text-zinc-200 text-xs uppercase">
              Argus C2
            </span>
          </div>

          {/* Live Engine Stream Pulse Indicator */}
          <div
            className={`flex items-center gap-1.5 px-2 py-0.5 rounded border transition-colors ${
              wsConnected
                ? "border-emerald-500/30 bg-emerald-950/20 text-emerald-400"
                : "border-amber-500/30 bg-amber-950/20 text-amber-400"
            }`}
            title={
              wsConnected
                ? "WebSocket real-time telemetry stream active"
                : "Reconnecting to event stream (/ws/v1/stream)..."
            }
          >
            <span className="relative flex h-2 w-2">
              {wsConnected && (
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
              )}
              <span
                className={`relative inline-flex rounded-full h-2 w-2 ${
                  wsConnected ? "bg-emerald-400" : "bg-amber-400"
                }`}
              />
            </span>
            <span className="text-[10px] font-semibold tracking-wide uppercase">
              {wsConnected ? "STREAM LIVE" : "CONNECTING..."}
            </span>
          </div>

          {/* Persistence Engine & WAL Pill */}
          <div
            className="flex items-center gap-1.5 px-2 py-0.5 rounded border border-[#222228] bg-[#121215] text-zinc-300"
            title={
              storageDiagnostics
                ? `DB Path: ${storageDiagnostics.db_path} | Journal: ${storageDiagnostics.journal_mode} | Size: ${(
                    storageDiagnostics.total_size_bytes / 1024
                  ).toFixed(1)} KB`
                : `Engine: ${storageBackend.toUpperCase()}`
            }
          >
            <Database className="h-3 w-3 text-blue-400 shrink-0" />
            <span className="text-[10px] text-zinc-400 uppercase">Engine:</span>
            <span className="text-[10px] font-medium text-zinc-200">
              {storageBackend.toUpperCase()}{" "}
              <span className="text-zinc-500">
                ({storageDiagnostics?.journal_mode?.toUpperCase() || "WAL"})
              </span>
            </span>
          </div>

          {/* Multi-Tenant Partition Pill */}
          <div className="hidden sm:flex items-center gap-1.5 px-2 py-0.5 rounded border border-[#222228] bg-[#121215] text-zinc-400">
            <Lock className="h-3 w-3 text-zinc-500 shrink-0" />
            <span className="text-[10px]">
              <span className="text-zinc-500">T:</span>
              <span className="text-zinc-300 font-medium ml-0.5">{tenantId}</span>
              <span className="text-zinc-600 mx-1">/</span>
              <span className="text-zinc-500">W:</span>
              <span className="text-zinc-300 font-medium ml-0.5">{workspaceId}</span>
            </span>
          </div>

          {/* Subsystem Readiness Badge */}
          <div
            className={`hidden md:flex items-center gap-1.5 px-2 py-0.5 rounded border ${
              systemReady
                ? "border-[#222228] bg-[#121215] text-zinc-300"
                : "border-rose-500/30 bg-rose-950/20 text-rose-400"
            }`}
            title={systemReady ? "All internal subsystems ready and healthy" : "Subsystem degraded"}
          >
            <CheckCircle2
              className={`h-3 w-3 ${systemReady ? "text-emerald-400" : "text-rose-400"} shrink-0`}
            />
            <span className="text-[10px] uppercase font-mono">
              {systemReady ? "READY" : "DEGRADED"}
            </span>
          </div>
        </div>

        {/* Center Sector: Real-Time Fleet Rollup & Standards */}
        <div className="flex flex-wrap items-center gap-2 sm:gap-3 text-zinc-400">
          {/* Active Fleet Metrics */}
          <div className="flex items-center gap-2 px-2.5 py-0.5 rounded border border-[#222228] bg-[#101014] text-[10px]">
            <span className="text-zinc-500 uppercase tracking-wider font-semibold">Fleet:</span>
            <span className="flex items-center gap-1 text-emerald-400 font-medium">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
              {activeCount} Active
            </span>
            <span className="text-zinc-600">•</span>
            <span className="flex items-center gap-1 text-amber-400 font-medium">
              <span className="h-1.5 w-1.5 rounded-full bg-amber-400" />
              {pausedCount} Paused
            </span>
            {trippedCount > 0 && (
              <>
                <span className="text-zinc-600">•</span>
                <span className="flex items-center gap-1 text-rose-400 font-medium">
                  <span className="h-1.5 w-1.5 rounded-full bg-rose-400" />
                  {trippedCount} Tripped
                </span>
              </>
            )}
            <span className="text-zinc-600">•</span>
            <span className="text-zinc-300 font-medium">
              ${totalCost.toFixed(4)}
            </span>
          </div>

          {/* Protocol Compliance Tags */}
          <div className="hidden xl:flex items-center gap-1.5 text-[10px] text-zinc-500">
            <span
              className="px-1.5 py-0.5 rounded bg-[#141418] border border-[#222228] hover:text-zinc-300 transition-colors"
              title="OpenTelemetry GenAI 1.28 Semantic Conventions"
            >
              OTel GenAI
            </span>
            <span
              className="px-1.5 py-0.5 rounded bg-[#141418] border border-[#222228] hover:text-zinc-300 transition-colors"
              title="Model Context Protocol 2024-11-05 Specification"
            >
              MCP
            </span>
            <span
              className="px-1.5 py-0.5 rounded bg-[#141418] border border-[#222228] hover:text-zinc-300 transition-colors"
              title="RFC 6902 JSON Patch Optimistic Concurrency"
            >
              RFC 6902
            </span>
            <span
              className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-emerald-950/20 border border-emerald-500/20 text-emerald-400"
              title="Cryptographically hash-chained SHA-256 audit log verified"
            >
              <ShieldCheck className="h-2.5 w-2.5 text-emerald-400" />
              SHA-256 Ledger
            </span>
          </div>
        </div>

        {/* Right Sector: Live Endpoints, Audit Trigger, and Attribution */}
        <div className="flex flex-wrap items-center gap-2.5 text-zinc-400">
          {/* Featured /docs Pitch Deck Button */}
          {onSelectView && (
            <button
              onClick={() => onSelectView("DOCS")}
              className="flex items-center gap-1.5 px-3 py-1 rounded-md bg-emerald-950/60 hover:bg-emerald-900/80 border border-emerald-500/40 text-emerald-300 hover:text-white text-[11px] font-mono font-medium transition-all shadow-[0_0_12px_rgba(16,185,129,0.15)] cursor-pointer"
              title="Open Live /docs Pitch Deck, Tech Whitepaper & Telemetry"
            >
              <Sparkles className="h-3 w-3 text-emerald-400" />
              <span>/docs Pitch Deck</span>
            </button>
          )}

          {/* Interactive Endpoints Group */}
          <div className="flex items-center gap-1 bg-[#121215] p-0.5 rounded border border-[#222228]">
            {onSelectView && (
              <button
                onClick={() => onSelectView("GUIDE")}
                className="px-2 py-0.5 rounded text-[10px] text-emerald-400 hover:text-emerald-200 hover:bg-[#1a1a20] transition-colors flex items-center gap-1 cursor-pointer"
                title="Open Operator Runbook & Architecture Guide"
              >
                <BookOpen className="h-2.5 w-2.5 text-emerald-400" />
                Guide
              </button>
            )}
            <a
              href="/api/docs"
              target="_blank"
              rel="noreferrer"
              className="px-2 py-0.5 rounded text-[10px] text-zinc-400 hover:text-zinc-100 hover:bg-[#1a1a20] transition-colors flex items-center gap-1"
              title="Interactive OpenAPI 3.1 Swagger UI"
            >
              <FileCode className="h-2.5 w-2.5 text-zinc-500" />
              API Specs
            </a>
            <a
              href="/metrics"
              target="_blank"
              rel="noreferrer"
              className="px-2 py-0.5 rounded text-[10px] text-zinc-400 hover:text-zinc-100 hover:bg-[#1a1a20] transition-colors flex items-center gap-1"
              title="Prometheus Metrics Exposition Endpoint"
            >
              <Activity className="h-2.5 w-2.5 text-zinc-500" />
              Metrics
            </a>
            <a
              href="/healthz"
              target="_blank"
              rel="noreferrer"
              className="px-2 py-0.5 rounded text-[10px] text-zinc-400 hover:text-zinc-100 hover:bg-[#1a1a20] transition-colors flex items-center gap-1"
              title="Kubernetes Liveness Probe (/healthz)"
            >
              <CheckCircle2 className="h-2.5 w-2.5 text-emerald-500" />
              Healthz
            </a>
            <a
              href="/readyz"
              target="_blank"
              rel="noreferrer"
              className="px-2 py-0.5 rounded text-[10px] text-zinc-400 hover:text-zinc-100 hover:bg-[#1a1a20] transition-colors flex items-center gap-1"
              title="Subsystem Readiness & Storage Probe (/readyz)"
            >
              <Cpu className="h-2.5 w-2.5 text-blue-400" />
              Readyz
            </a>
          </div>

          {/* Export Audit Log Button */}
          {selectedSessionId && (
            <button
              onClick={handleExportClick}
              className="inline-flex items-center gap-1 px-2 py-1 rounded bg-[#18181e] hover:bg-[#22222a] border border-[#2a2a34] text-zinc-200 text-[10px] font-medium transition-colors cursor-pointer"
              title={`Download tamper-evident SHA-256 audit ledger for session ${selectedSessionId}`}
            >
              <Download className="h-2.5 w-2.5 text-emerald-400" />
              Audit Export
            </button>
          )}

          {/* License & Copyright */}
          <div className="flex items-center gap-1.5 pl-1.5 text-[10px] text-zinc-500">
            <span className="px-1.5 py-0.5 rounded border border-[#222228] bg-[#121215] text-zinc-400 font-mono">
              Apache-2.0
            </span>
            <span className="text-zinc-600">•</span>
            <span className="hidden sm:inline text-zinc-500 font-sans">
              © 2026 Argus Contributors
            </span>
          </div>
        </div>
      </div>
    </footer>
  );
};
