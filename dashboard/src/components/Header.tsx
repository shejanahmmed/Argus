import React from "react";
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
} from "lucide-react";
import { AgentSession, ViewMode } from "../types";

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
}) => {
  const activeCount = sessions.filter((s) => s.status === "RUNNING").length;
  const pausedCount = sessions.filter((s) => s.status === "PAUSED_C2").length;
  const trippedCount = sessions.filter(
    (s) => s.status === "TRIPPED_LOOP" || s.status === "TRIPPED_BUDGET"
  ).length;
  const totalCost = sessions.reduce((acc, s) => acc + s.accumulated_cost_usd, 0);

  const navTabs: Array<{ id: ViewMode; label: string; icon: React.ReactNode }> = [
    { id: "ALL", label: "Overview", icon: <Layers className="h-4 w-4" /> },
    { id: "TOPOLOGY", label: "Topology & Traces", icon: <GitBranch className="h-4 w-4" /> },
    { id: "C2_LAB", label: "C2 Governance", icon: <SlidersHorizontal className="h-4 w-4" /> },
    { id: "FINOPS", label: "FinOps & ROI", icon: <CircleDollarSign className="h-4 w-4" /> },
  ];

  return (
    <header className="border-b border-zinc-800 bg-[#09090b] sticky top-0 z-30">
      {/* Top Navbar */}
      <div className="max-w-[1920px] mx-auto px-6 py-3 flex flex-wrap items-center justify-between gap-4 border-b border-zinc-800/60">
        {/* Brand & Workspace */}
        <div className="flex items-center gap-3">
          <div className="flex h-8 w-8 items-center justify-center rounded-md bg-zinc-800 border border-zinc-700 text-zinc-100 shadow-sm">
            <Shield className="h-4 w-4 text-emerald-400" />
          </div>
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold tracking-tight text-white">Argus</span>
            <span className="text-zinc-600 text-xs">/</span>
            <span className="text-xs text-zinc-400">AgentOps & C2</span>
            <span className="ml-2 rounded-full bg-zinc-800 px-2 py-0.5 text-[11px] font-medium text-zinc-300 border border-zinc-700">
              default-workspace
            </span>
          </div>
        </div>

        {/* View Navigation Tabs */}
        <nav className="flex items-center gap-1 rounded-lg bg-zinc-900 p-1 border border-zinc-800">
          {navTabs.map((tab) => {
            const isActive = activeView === tab.id;
            return (
              <button
                key={tab.id}
                onClick={() => onSelectView(tab.id)}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-colors cursor-pointer ${
                  isActive
                    ? "bg-zinc-800 text-white shadow-sm"
                    : "text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/50"
                }`}
              >
                {tab.icon}
                <span>{tab.label}</span>
              </button>
            );
          })}
        </nav>

        {/* Action Controls & Stream Health */}
        <div className="flex items-center gap-2.5">
          <button
            onClick={onSeedScenario}
            disabled={seeding}
            className="flex items-center gap-1.5 rounded-md bg-white hover:bg-zinc-200 text-zinc-950 px-3 py-1.5 text-xs font-semibold shadow-sm transition-all cursor-pointer disabled:opacity-50"
          >
            <Play className="h-3 w-3 fill-zinc-950" />
            <span>{seeding ? "Seeding..." : "Seed Demo Fleet"}</span>
          </button>

          <button
            onClick={onSimulateLoopStep}
            disabled={!hasSelectedSession}
            title="Inject an identical repeated tool step to trip the loop detector"
            className="flex items-center gap-1.5 rounded-md border border-zinc-700 bg-zinc-900 hover:bg-zinc-800 text-zinc-200 px-3 py-1.5 text-xs font-medium transition-colors cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
          >
            <RotateCcw className="h-3 w-3 text-rose-400" />
            <span>Simulate Loop</span>
          </button>

          <button
            onClick={onSimulateMcpAttack}
            disabled={!hasSelectedSession}
            title="Dispatch a destructive MCP tool call to test C2 interception"
            className="flex items-center gap-1.5 rounded-md border border-zinc-700 bg-zinc-900 hover:bg-zinc-800 text-zinc-200 px-3 py-1.5 text-xs font-medium transition-colors cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
          >
            <ShieldAlert className="h-3.5 w-3.5 text-amber-400" />
            <span>Test MCP Gate</span>
          </button>

          <div
            className={`flex items-center gap-2 rounded-md border px-2.5 py-1 text-xs ${
              wsConnected
                ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-400"
                : "border-rose-500/30 bg-rose-500/10 text-rose-400"
            }`}
          >
            <span
              className={`h-1.5 w-1.5 rounded-full ${
                wsConnected ? "bg-emerald-400" : "bg-rose-400"
              }`}
            />
            <span className="text-[11px] font-medium">
              {wsConnected ? "EventBus Connected" : "Disconnected"}
            </span>
          </div>
        </div>
      </div>

      {/* KPI Metric Strip */}
      <div className="max-w-[1920px] mx-auto px-6 py-2.5 flex flex-wrap items-center justify-between gap-4 text-xs text-zinc-400">
        <div className="flex items-center gap-6">
          <div className="flex items-center gap-2">
            <span className="text-zinc-500 font-medium">Running:</span>
            <span className="font-semibold text-zinc-100">{activeCount}</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-zinc-500 font-medium">Paused (C2):</span>
            <span className="font-semibold text-amber-400">{pausedCount}</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-zinc-500 font-medium">Tripped:</span>
            <span className={`font-semibold ${trippedCount > 0 ? "text-rose-400" : "text-zinc-100"}`}>
              {trippedCount}
            </span>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-zinc-500 font-medium">Pending Approvals:</span>
            <span className={`font-semibold ${pendingInterventionsCount > 0 ? "text-amber-400" : "text-zinc-100"}`}>
              {pendingInterventionsCount}
            </span>
          </div>
        </div>

        <div className="flex items-center gap-4">
          <div className="flex items-center gap-1.5 text-zinc-400">
            <span className="text-zinc-500">Fleet Spend:</span>
            <span className="font-mono font-semibold text-zinc-100">${totalCost.toFixed(4)}</span>
          </div>
          <div className="flex items-center gap-1.5 text-zinc-500 text-[11px]">
            <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" />
            <span>Zero-Spend Local Infrastructure</span>
          </div>
        </div>
      </div>
    </header>
  );
};
