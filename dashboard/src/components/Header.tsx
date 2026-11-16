import React, { useState, useRef, useEffect } from "react";
import {
  Shield,
  Play,
  RotateCcw,
  ShieldAlert,
  Layers,
  GitBranch,
  SlidersHorizontal,
  CircleDollarSign,
  CheckCircle2,
  Key,
  X,
  Lock,
  Database,
  FlaskConical,
  ChevronDown,
} from "lucide-react";
import { AgentSession, ViewMode, StorageDiagnostics } from "../types";

interface HeaderProps {
  wsConnected: boolean;
  sessions: AgentSession[];
  pendingInterventionsCount: number;
  activeView: ViewMode;
  onSelectView: (view: ViewMode) => void;
  onSeedScenario: () => void;
  onSimulateLoopStep: () => void;
  onSimulateMcpAttack: () => void;
  seeding: boolean;
  hasSelectedSession: boolean;
  tenantId: string;
  workspaceId: string;
  actorId: string;
  authToken: string;
  onSaveAuthConfig: (tenant: string, workspace: string, actor: string, token: string) => void;
  storageBackend?: string;
  storageDiagnostics?: StorageDiagnostics | null;
  systemReady?: boolean;
  onFlushWalCheckpoint?: () => void;
}

export const Header: React.FC<HeaderProps> = ({
  wsConnected,
  sessions,
  pendingInterventionsCount,
  activeView,
  onSelectView,
  onSeedScenario,
  onSimulateLoopStep,
  onSimulateMcpAttack,
  seeding,
  hasSelectedSession,
  tenantId,
  workspaceId,
  actorId,
  authToken,
  onSaveAuthConfig,
  storageBackend = "sqlite",
  storageDiagnostics,
  systemReady = true,
  onFlushWalCheckpoint,
}) => {
  const [showAuthModal, setShowAuthModal] = useState<boolean>(false);
  const [showStorageModal, setShowStorageModal] = useState<boolean>(false);
  const [showSimMenu, setShowSimMenu] = useState<boolean>(false);
  const simMenuRef = useRef<HTMLDivElement>(null);

  const [modalTenant, setModalTenant] = useState<string>(tenantId);
  const [modalWorkspace, setModalWorkspace] = useState<string>(workspaceId);
  const [modalActor, setModalActor] = useState<string>(actorId);
  const [modalToken, setModalToken] = useState<string>(authToken);

  const activeCount = sessions.filter((s) => s.status === "RUNNING").length;
  const pausedCount = sessions.filter((s) => s.status === "PAUSED_C2").length;
  const trippedCount = sessions.filter(
    (s) => s.status === "TRIPPED_LOOP" || s.status === "TRIPPED_BUDGET"
  ).length;
  const totalCost = sessions.reduce((acc, s) => acc + s.accumulated_cost_usd, 0);

  // Close simulation menu when clicking outside
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (simMenuRef.current && !simMenuRef.current.contains(e.target as Node)) {
        setShowSimMenu(false);
      }
    };
    if (showSimMenu) {
      document.addEventListener("mousedown", handleClickOutside);
      return () => document.removeEventListener("mousedown", handleClickOutside);
    }
  }, [showSimMenu]);

  const handleOpenAuth = () => {
    setModalTenant(tenantId);
    setModalWorkspace(workspaceId);
    setModalActor(actorId);
    setModalToken(authToken);
    setShowAuthModal(true);
  };

  const handleSaveAuth = () => {
    onSaveAuthConfig(modalTenant.trim(), modalWorkspace.trim(), modalActor.trim(), modalToken.trim());
    setShowAuthModal(false);
  };

  const navTabs: Array<{ id: ViewMode; label: string; icon: React.ReactNode }> = [
    { id: "ALL", label: "Overview", icon: <Layers className="h-3.5 w-3.5" /> },
    { id: "TOPOLOGY", label: "Topology & Traces", icon: <GitBranch className="h-3.5 w-3.5" /> },
    { id: "C2_LAB", label: "C2 Governance", icon: <SlidersHorizontal className="h-3.5 w-3.5" /> },
    { id: "FINOPS", label: "FinOps & ROI", icon: <CircleDollarSign className="h-3.5 w-3.5" /> },
  ];

  return (
    <header className="border-b border-[#222228] bg-[#09090b] sticky top-0 z-30">
      {/* Top Command Bar */}
      <div className="max-w-[1920px] mx-auto px-6 py-2.5 flex flex-wrap items-center justify-between gap-4">
        {/* Left: Brand & Tenant Context */}
        <div className="flex items-center gap-3">
          <div className="flex h-7 w-7 items-center justify-center rounded-md bg-[#141418] border border-[#27272a] text-zinc-100 shadow-sm">
            <Shield className="h-3.5 w-3.5 text-emerald-400" />
          </div>
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold tracking-tight text-white font-sans">Argus</span>
            <span className="rounded bg-zinc-800/80 px-1.5 py-0.5 text-[10px] font-mono font-medium text-zinc-400 border border-zinc-700/50">
              C2
            </span>
            <span className="text-zinc-700 text-xs">|</span>
            <button
              onClick={handleOpenAuth}
              title="Configure Tenant ID, Workspace ID, Operator ID, and Token"
              className="flex items-center gap-1.5 rounded-md bg-[#141418] hover:bg-[#1a1a20] px-2 py-1 text-[11px] font-mono text-zinc-300 border border-[#222228] transition-colors cursor-pointer"
            >
              <span className="text-zinc-400">{tenantId}</span>
              <span className="text-zinc-600">/</span>
              <span className="text-zinc-300">{workspaceId}</span>
              {authToken ? (
                <Lock className="h-2.5 w-2.5 text-emerald-400 ml-0.5" />
              ) : (
                <Key className="h-2.5 w-2.5 text-zinc-500 ml-0.5" />
              )}
            </button>
          </div>
        </div>

        {/* Center: Segmented View Navigation */}
        <nav className="flex items-center gap-0.5 rounded-lg bg-[#0d0d10] p-1 border border-[#222228]">
          {navTabs.map((tab) => {
            const isActive = activeView === tab.id;
            return (
              <button
                key={tab.id}
                onClick={() => onSelectView(tab.id)}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-colors cursor-pointer ${
                  isActive
                    ? "bg-[#1e1e24] text-white shadow-xs"
                    : "text-zinc-400 hover:text-zinc-200 hover:bg-[#141418]"
                }`}
              >
                {tab.icon}
                <span>{tab.label}</span>
              </button>
            );
          })}
        </nav>

        {/* Right: Simulation Toolkit & System Diagnostics */}
        <div className="flex items-center gap-2">
          {/* Simulation Toolkit Dropdown */}
          <div className="relative" ref={simMenuRef}>
            <button
              onClick={() => setShowSimMenu((prev) => !prev)}
              className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-xs font-medium border transition-colors cursor-pointer ${
                showSimMenu
                  ? "bg-zinc-800 border-zinc-600 text-white"
                  : "bg-[#141418] border-[#222228] text-zinc-300 hover:text-white hover:border-[#2e2e38]"
              }`}
              title="Simulate agent workloads, circuit breakers, and MCP tool overrides"
            >
              <FlaskConical className="h-3.5 w-3.5 text-zinc-400" />
              <span>Simulation</span>
              <ChevronDown
                className={`h-3 w-3 text-zinc-500 transition-transform ${
                  showSimMenu ? "rotate-180" : ""
                }`}
              />
            </button>

            {showSimMenu && (
              <div className="absolute right-0 mt-2 w-72 rounded-lg border border-[#27272a] bg-[#121215] p-1.5 shadow-2xl z-50 animate-in fade-in zoom-in-95">
                <div className="px-2.5 py-1.5 border-b border-[#222228] mb-1">
                  <span className="text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
                    Simulation & Demo Sandbox
                  </span>
                </div>

                <button
                  onClick={() => {
                    onSeedScenario();
                    setShowSimMenu(false);
                  }}
                  disabled={seeding}
                  className="w-full flex items-start gap-2.5 p-2 rounded-md hover:bg-[#1a1a20] text-left transition-colors cursor-pointer disabled:opacity-40"
                >
                  <div className="p-1 rounded bg-zinc-800 text-zinc-200 mt-0.5">
                    <Play className="h-3 w-3 fill-zinc-200" />
                  </div>
                  <div>
                    <div className="text-xs font-medium text-zinc-200">
                      {seeding ? "Seeding Fleet..." : "Seed Demo Fleet"}
                    </div>
                    <div className="text-[11px] text-zinc-500">
                      Populate 3 LangGraph sessions with DAG spans & checkpoints
                    </div>
                  </div>
                </button>

                <button
                  onClick={() => {
                    onSimulateLoopStep();
                    setShowSimMenu(false);
                  }}
                  disabled={!hasSelectedSession}
                  className="w-full flex items-start gap-2.5 p-2 rounded-md hover:bg-[#1a1a20] text-left transition-colors cursor-pointer disabled:opacity-40"
                >
                  <div className="p-1 rounded bg-rose-500/10 text-rose-400 border border-rose-500/20 mt-0.5">
                    <RotateCcw className="h-3 w-3" />
                  </div>
                  <div>
                    <div className="text-xs font-medium text-zinc-200">Simulate Loop Step</div>
                    <div className="text-[11px] text-zinc-500">
                      Inject an oscillatory tool cycle to trigger circuit breaker
                    </div>
                  </div>
                </button>

                <button
                  onClick={() => {
                    onSimulateMcpAttack();
                    setShowSimMenu(false);
                  }}
                  disabled={!hasSelectedSession}
                  className="w-full flex items-start gap-2.5 p-2 rounded-md hover:bg-[#1a1a20] text-left transition-colors cursor-pointer disabled:opacity-40"
                >
                  <div className="p-1 rounded bg-amber-500/10 text-amber-400 border border-amber-500/20 mt-0.5">
                    <ShieldAlert className="h-3 w-3" />
                  </div>
                  <div>
                    <div className="text-xs font-medium text-zinc-200">Test MCP Guardrail</div>
                    <div className="text-[11px] text-zinc-500">
                      Dispatch high-risk MCP tool call for human C2 override
                    </div>
                  </div>
                </button>
              </div>
            )}
          </div>

          {/* Storage Backend Badge */}
          <button
            onClick={() => setShowStorageModal(true)}
            title="Click to view live database diagnostics"
            className="flex items-center gap-1.5 rounded-md border border-[#222228] bg-[#141418] hover:bg-[#1a1a20] px-2.5 py-1.5 text-xs cursor-pointer transition-colors"
          >
            <Database className="h-3.5 w-3.5 text-zinc-400" />
            <span className="text-[11px] font-mono text-zinc-200">
              {storageBackend === "sqlite"
                ? "SQLite (WAL)"
                : storageBackend === "postgres"
                ? "PostgreSQL"
                : "In-Memory"}
            </span>
            <span
              className={`h-1.5 w-1.5 rounded-full ${
                systemReady ? "bg-emerald-400" : "bg-amber-400"
              }`}
            />
          </button>

          {/* WebSocket EventBus Indicator */}
          <div
            title={
              wsConnected
                ? "EventBus WebSocket connected and streaming"
                : "EventBus disconnected"
            }
            className="flex items-center gap-1.5 rounded-md border border-[#222228] bg-[#141418] px-2.5 py-1.5 text-xs"
          >
            <span
              className={`h-1.5 w-1.5 rounded-full ${
                wsConnected ? "bg-emerald-400" : "bg-rose-400"
              }`}
            />
            <span className="text-[11px] font-medium text-zinc-400">
              {wsConnected ? "Live" : "Offline"}
            </span>
          </div>
        </div>
      </div>

      {/* Streamlined High-Density KPI Ribbon */}
      <div className="border-t border-[#1a1a20] bg-[#0c0c0f] px-6 py-1.5">
        <div className="max-w-[1920px] mx-auto flex flex-wrap items-center justify-between gap-4 text-[11px]">
          <div className="flex items-center gap-5">
            <div className="flex items-center gap-1.5">
              <span className="text-zinc-500">RUNNING:</span>
              <span className="font-mono font-semibold text-emerald-400">{activeCount}</span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="text-zinc-500">PAUSED:</span>
              <span className="font-mono font-semibold text-amber-400">{pausedCount}</span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="text-zinc-500">TRIPPED:</span>
              <span
                className={`font-mono font-semibold ${
                  trippedCount > 0 ? "text-rose-400" : "text-zinc-400"
                }`}
              >
                {trippedCount}
              </span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="text-zinc-500">PENDING C2:</span>
              <span
                className={`font-mono font-semibold ${
                  pendingInterventionsCount > 0 ? "text-amber-400" : "text-zinc-400"
                }`}
              >
                {pendingInterventionsCount}
              </span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="text-zinc-500">FLEET SPEND:</span>
              <span className="font-mono font-semibold text-zinc-200">
                ${totalCost.toFixed(4)}
              </span>
            </div>
          </div>

          <div className="flex items-center gap-2 text-zinc-500 text-[10px] font-mono">
            <CheckCircle2 className="h-3 w-3 text-emerald-400" />
            <span>$0 Zero-Spend Infrastructure Active</span>
          </div>
        </div>
      </div>

      {/* Tenant Context & Security Token Modal */}
      {showAuthModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-xs p-4">
          <div className="w-full max-w-md rounded-xl border border-[#27272a] bg-[#111114] p-6 shadow-2xl">
            <div className="flex items-center justify-between pb-4 border-b border-[#222228]">
              <div className="flex items-center gap-2">
                <Lock className="h-4 w-4 text-emerald-400" />
                <h3 className="text-sm font-semibold text-white">Tenant & Security Context</h3>
              </div>
              <button
                onClick={() => setShowAuthModal(false)}
                className="rounded-md p-1 text-zinc-400 hover:text-white hover:bg-zinc-800 transition-colors cursor-pointer"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <div className="py-4 space-y-4">
              <div>
                <label className="block text-xs font-medium text-zinc-300 mb-1.5">
                  Tenant Identifier
                </label>
                <input
                  type="text"
                  value={modalTenant}
                  onChange={(e) => setModalTenant(e.target.value)}
                  placeholder="e.g. default_tenant"
                  className="w-full rounded-md border border-[#27272a] bg-[#141418] px-3 py-1.5 text-xs text-white placeholder-zinc-500 focus:border-zinc-500 focus:outline-hidden"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-zinc-300 mb-1.5">
                  Workspace Identifier
                </label>
                <input
                  type="text"
                  value={modalWorkspace}
                  onChange={(e) => setModalWorkspace(e.target.value)}
                  placeholder="e.g. default_workspace"
                  className="w-full rounded-md border border-[#27272a] bg-[#141418] px-3 py-1.5 text-xs text-white placeholder-zinc-500 focus:border-zinc-500 focus:outline-hidden"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-zinc-300 mb-1.5">
                  Operator / Actor Identifier
                </label>
                <input
                  type="text"
                  value={modalActor}
                  onChange={(e) => setModalActor(e.target.value)}
                  placeholder="e.g. operator_admin or sre_alice"
                  className="w-full rounded-md border border-[#27272a] bg-[#141418] px-3 py-1.5 text-xs text-white placeholder-zinc-500 focus:border-zinc-500 focus:outline-hidden"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-zinc-300 mb-1.5">
                  Argus HMAC Bearer Token
                </label>
                <textarea
                  rows={3}
                  value={modalToken}
                  onChange={(e) => setModalToken(e.target.value)}
                  placeholder="argus_tok.eyJhY3Rvcl9pZCI6... (Optional in dev, required in production)"
                  className="w-full rounded-md border border-[#27272a] bg-[#141418] px-3 py-1.5 font-mono text-[11px] text-zinc-200 placeholder-zinc-600 focus:border-zinc-500 focus:outline-hidden resize-none"
                />
                <p className="mt-1 text-[10px] text-zinc-500">
                  Generate tokens via CLI:{" "}
                  <code className="text-zinc-400">
                    python -m argus auth issue-token --tenant ...
                  </code>
                </p>
              </div>
            </div>

            <div className="flex items-center justify-between pt-4 border-t border-[#222228]">
              {modalToken ? (
                <button
                  type="button"
                  onClick={() => setModalToken("")}
                  className="text-xs text-rose-400 hover:text-rose-300 underline cursor-pointer"
                >
                  Clear Token
                </button>
              ) : (
                <div />
              )}
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => setShowAuthModal(false)}
                  className="rounded-md border border-[#27272a] bg-[#141418] px-3 py-1.5 text-xs font-medium text-zinc-300 hover:bg-[#1a1a20] transition-colors cursor-pointer"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={handleSaveAuth}
                  className="rounded-md bg-white hover:bg-zinc-200 text-zinc-950 px-3 py-1.5 text-xs font-semibold shadow-xs transition-all cursor-pointer"
                >
                  Save & Apply
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Persistence Engine Diagnostics Modal */}
      {showStorageModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-xs p-4">
          <div className="w-full max-w-lg rounded-xl border border-[#27272a] bg-[#111114] p-6 shadow-2xl">
            <div className="flex items-center justify-between pb-4 border-b border-[#222228]">
              <div className="flex items-center gap-2">
                <Database className="h-4 w-4 text-emerald-400" />
                <h3 className="text-sm font-semibold text-white">
                  Persistence Engine Diagnostics
                </h3>
              </div>
              <button
                onClick={() => setShowStorageModal(false)}
                className="rounded-md p-1 text-zinc-400 hover:text-white hover:bg-zinc-800 transition-colors cursor-pointer"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <div className="py-4 space-y-4">
              {/* Backend & Integrity Info */}
              <div className="grid grid-cols-2 gap-3">
                <div className="rounded-lg border border-[#222228] bg-[#141418] p-3">
                  <span className="text-[11px] text-zinc-500 block mb-1">Storage Backend</span>
                  <span className="text-xs font-semibold text-zinc-200">
                    {storageBackend === "sqlite"
                      ? "WAL-Mode SQLite 3"
                      : storageBackend === "postgres"
                      ? "PostgreSQL 16"
                      : "In-Memory Store"}
                  </span>
                </div>
                <div className="rounded-lg border border-[#222228] bg-[#141418] p-3">
                  <span className="text-[11px] text-zinc-500 block mb-1">Integrity Status</span>
                  <div className="flex items-center gap-1.5">
                    <span className="h-2 w-2 rounded-full bg-emerald-400" />
                    <span className="text-xs font-semibold text-emerald-400">
                      {storageDiagnostics?.integrity_check ||
                        (systemReady ? "Verified (ACID)" : "Degraded")}
                    </span>
                  </div>
                </div>
              </div>

              {/* Database Metrics */}
              {storageDiagnostics && (
                <div className="rounded-lg border border-[#222228] bg-[#141418] p-3 space-y-2 text-xs">
                  <div className="flex justify-between text-zinc-400">
                    <span>Database Path:</span>
                    <span className="font-mono text-zinc-200 text-[11px]">
                      {storageDiagnostics.db_path}
                    </span>
                  </div>
                  <div className="flex justify-between text-zinc-400">
                    <span>Journal Mode:</span>
                    <span className="font-mono text-emerald-400 font-semibold">
                      {storageDiagnostics.journal_mode.toUpperCase()}
                    </span>
                  </div>
                  <div className="flex justify-between text-zinc-400">
                    <span>Disk Footprint:</span>
                    <span className="font-mono text-zinc-200">
                      {(storageDiagnostics.total_size_bytes / 1024).toFixed(1)} KB (
                      {storageDiagnostics.page_count} pages)
                    </span>
                  </div>
                </div>
              )}

              {/* Entity Row Counts */}
              <div className="rounded-lg border border-[#222228] bg-[#141418] p-3">
                <span className="text-[11px] text-zinc-500 font-medium block mb-2">
                  Entity Record Inventory
                </span>
                <div className="grid grid-cols-3 gap-2 text-center text-xs">
                  <div className="rounded bg-[#1a1a20] p-2 border border-[#222228]">
                    <span className="text-zinc-400 text-[10px] block">Sessions</span>
                    <span className="font-mono font-semibold text-white">
                      {storageDiagnostics?.table_counts.sessions ?? sessions.length}
                    </span>
                  </div>
                  <div className="rounded bg-[#1a1a20] p-2 border border-[#222228]">
                    <span className="text-zinc-400 text-[10px] block">Checkpoints</span>
                    <span className="font-mono font-semibold text-white">
                      {storageDiagnostics?.table_counts.checkpoints ?? "-"}
                    </span>
                  </div>
                  <div className="rounded bg-[#1a1a20] p-2 border border-[#222228]">
                    <span className="text-zinc-400 text-[10px] block">Telemetry Spans</span>
                    <span className="font-mono font-semibold text-white">
                      {storageDiagnostics?.table_counts.spans ?? "-"}
                    </span>
                  </div>
                  <div className="rounded bg-[#1a1a20] p-2 border border-[#222228]">
                    <span className="text-zinc-400 text-[10px] block">Budget Ledgers</span>
                    <span className="font-mono font-semibold text-white">
                      {storageDiagnostics?.table_counts.budgets ?? "-"}
                    </span>
                  </div>
                  <div className="rounded bg-[#1a1a20] p-2 col-span-2 border border-[#222228]">
                    <span className="text-zinc-400 text-[10px] block">SHA-256 Audit Entries</span>
                    <span className="font-mono font-semibold text-emerald-400">
                      {storageDiagnostics?.table_counts.audit_entries ?? "-"} blocks
                    </span>
                  </div>
                </div>
              </div>
            </div>

            <div className="flex items-center justify-between pt-4 border-t border-[#222228]">
              <span className="text-[11px] text-zinc-500 font-mono">
                $0 Monolithic Architecture
              </span>
              <div className="flex items-center gap-2">
                {storageBackend === "sqlite" && onFlushWalCheckpoint && (
                  <button
                    type="button"
                    onClick={onFlushWalCheckpoint}
                    className="rounded-md border border-[#27272a] bg-[#141418] px-3 py-1.5 text-xs font-medium text-zinc-300 hover:bg-[#1a1a20] transition-colors cursor-pointer"
                  >
                    Flush WAL Checkpoint
                  </button>
                )}
                <button
                  type="button"
                  onClick={() => setShowStorageModal(false)}
                  className="rounded-md bg-white hover:bg-zinc-200 text-zinc-950 px-3 py-1.5 text-xs font-semibold shadow-xs transition-all cursor-pointer"
                >
                  Close
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </header>
  );
};
