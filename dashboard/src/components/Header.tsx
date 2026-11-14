import React from "react";
import {
  Activity,
  ShieldAlert,
  Cpu,
  DollarSign,
  Radio,
  Sparkles,
  Repeat,
  ShieldCheck,
  Layers,
  GitBranch,
  Sliders,
  BarChart3,
  PauseCircle,
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

  const navItems: Array<{ id: ViewMode; label: string; icon: React.ReactNode }> = [
    { id: "ALL", label: "00 // COMMAND CENTER", icon: <Layers className="h-3.5 w-3.5" /> },
    { id: "TOPOLOGY", label: "01 // TOPOLOGY & WATERFALL", icon: <GitBranch className="h-3.5 w-3.5" /> },
    { id: "C2_LAB", label: "02 // C2 STATE & MCP LAB", icon: <Sliders className="h-3.5 w-3.5" /> },
    { id: "FINOPS", label: "03 // FINOPS & HF PARETO", icon: <BarChart3 className="h-3.5 w-3.5" /> },
  ];

  return (
    <header className="border-b border-[#262626] bg-[#000000] sticky top-0 z-30">
      {/* Top Tier: Brand Identity, Simulation Actions & Stream Status */}
      <div className="flex flex-wrap items-center justify-between gap-4 px-6 py-3.5 border-b border-[#171717]">
        <div className="flex items-center gap-3.5">
          <div className="flex h-10 w-10 items-center justify-center border border-[#00ff66] bg-[#001808] shadow-[0_0_15px_rgba(0,255,102,0.18)]">
            <Radio className="h-5 w-5 text-[#00ff66]" />
          </div>
          <div>
            <div className="flex items-center gap-2.5">
              <span className="text-base font-bold tracking-[0.18em] text-white">
                ARGUS <span className="text-[#00ff66]">//</span> C2 CONTROL PLANE
              </span>
              <span className="border border-[#2e2e2e] bg-[#0c0c0c] px-2 py-0.5 text-[10px] font-semibold tracking-wider text-[#a3a3a3]">
                v1.0-ENTERPRISE
              </span>
              <span className="hidden sm:inline-flex items-center gap-1 border border-[#00ff66]/40 bg-[#001408] px-2 py-0.5 text-[10px] text-[#00ff66]">
                <ShieldCheck className="h-3 w-3" />
                RBAC: ADMIN // ZERO-SPEND OSS
              </span>
            </div>
            <div className="text-[11px] tracking-widest text-[#737373] mt-0.5">
              AUTONOMOUS AGENT GOVERNANCE • 3-TIER CIRCUIT BREAKER • MCP PROXY • RFC 6902 C2
            </div>
          </div>
        </div>

        {/* Live Action & Simulation Controls */}
        <div className="flex flex-wrap items-center gap-2.5 text-xs font-mono">
          <button
            onClick={onSeedScenario}
            disabled={seeding}
            className="flex items-center gap-2 border border-[#00ff66] bg-[#001a09] px-3.5 py-2 text-[#00ff66] hover:bg-[#00ff66] hover:text-black font-bold tracking-wider transition-all cursor-pointer disabled:opacity-50"
          >
            <Sparkles className="h-3.5 w-3.5" />
            <span>{seeding ? "SEEDING FLEET..." : "SEED DEMO SCENARIO"}</span>
          </button>

          <button
            onClick={onSimulateLoopStep}
            disabled={!hasSelectedSession}
            title="Inject a repetitive tool-call span into the selected session to trigger the 3-Tier Loop Breaker"
            className="flex items-center gap-1.5 border border-[#ff3333]/80 bg-[#1a0303] px-3 py-2 text-[#ff5555] hover:bg-[#ff3333] hover:text-black font-bold tracking-wider transition-all cursor-pointer disabled:opacity-35 disabled:cursor-not-allowed"
          >
            <Repeat className="h-3.5 w-3.5" />
            <span>+ SIMULATE LOOP STEP</span>
          </button>

          <button
            onClick={onSimulateMcpAttack}
            disabled={!hasSelectedSession}
            title="Dispatch a high-risk MCP tools/call to trigger pre-execution C2 interception"
            className="flex items-center gap-1.5 border border-[#ffb000]/80 bg-[#191000] px-3 py-2 text-[#ffb000] hover:bg-[#ffb000] hover:text-black font-bold tracking-wider transition-all cursor-pointer disabled:opacity-35 disabled:cursor-not-allowed"
          >
            <ShieldAlert className="h-3.5 w-3.5" />
            <span>+ SIMULATE MCP GATE</span>
          </button>

          <div
            className={`flex items-center gap-2 border px-3 py-2 ${
              wsConnected
                ? "border-[#00ff66]/60 bg-[#031207] text-[#00ff66]"
                : "border-[#ff3333] bg-[#1a0303] text-[#ff3333]"
            }`}
          >
            <span
              className={`h-2 w-2 rounded-full ${
                wsConnected ? "bg-[#00ff66] pulse-green" : "bg-[#ff3333]"
              }`}
            />
            <span className="font-bold tracking-wider text-[11px]">
              {wsConnected ? "EVENTBUS LIVE" : "OFFLINE"}
            </span>
          </div>
        </div>
      </div>

      {/* Bottom Tier: View Switcher Tabs & Telemetry KPI Strip */}
      <div className="flex flex-wrap items-center justify-between gap-4 px-6 py-2 bg-[#040404]">
        <nav className="flex flex-wrap items-center gap-1.5">
          {navItems.map((item) => {
            const isActive = activeView === item.id;
            return (
              <button
                key={item.id}
                onClick={() => onSelectView(item.id)}
                className={`flex items-center gap-2 px-3.5 py-1.5 text-[11px] font-bold tracking-wider border transition-all cursor-pointer ${
                  isActive
                    ? "border-[#00ff66] bg-[#00ff66] text-black"
                    : "border-[#1f1f1f] bg-[#080808] text-[#888888] hover:border-[#444444] hover:text-white"
                }`}
              >
                {item.icon}
                <span>{item.label}</span>
              </button>
            );
          })}
        </nav>

        <div className="flex flex-wrap items-center gap-2.5 text-[11px] font-mono">
          <div className="flex items-center gap-2 border border-[#222222] bg-[#080808] px-3 py-1">
            <Cpu className="h-3.5 w-3.5 text-[#00ff66]" />
            <span className="text-[#737373]">RUNNING:</span>
            <span className="font-bold text-white">{activeCount}</span>
          </div>

          <div className="flex items-center gap-2 border border-[#222222] bg-[#080808] px-3 py-1">
            <PauseCircle className="h-3.5 w-3.5 text-[#ffb000]" />
            <span className="text-[#737373]">PAUSED C2:</span>
            <span className="font-bold text-[#ffb000]">{pausedCount}</span>
          </div>

          <div
            className={`flex items-center gap-2 border px-3 py-1 ${
              trippedCount > 0
                ? "border-[#ff3333] bg-[#1f0303] text-[#ff3333] pulse-red"
                : "border-[#222222] bg-[#080808] text-[#737373]"
            }`}
          >
            <ShieldAlert className="h-3.5 w-3.5" />
            <span>TRIPPED:</span>
            <span className="font-bold">{trippedCount}</span>
          </div>

          <div
            className={`flex items-center gap-2 border px-3 py-1 ${
              pendingInterventionsCount > 0
                ? "border-[#ffb000] bg-[#1c1100] text-[#ffb000]"
                : "border-[#222222] bg-[#080808] text-[#737373]"
            }`}
          >
            <Activity className="h-3.5 w-3.5" />
            <span>PENDING OVERRIDES:</span>
            <span className="font-bold">{pendingInterventionsCount}</span>
          </div>

          <div className="flex items-center gap-2 border border-[#222222] bg-[#080808] px-3 py-1">
            <DollarSign className="h-3.5 w-3.5 text-[#00e5ff]" />
            <span className="text-[#737373]">FLEET SPEND:</span>
            <span className="font-bold text-[#00e5ff]">${totalCost.toFixed(4)}</span>
          </div>
        </div>
      </div>
    </header>
  );
};
