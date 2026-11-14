import React from "react";
import { Activity, ShieldAlert, Cpu, DollarSign, Radio, Sparkles } from "lucide-react";
import { AgentSession } from "../types";

interface HeaderProps {
  wsConnected: boolean;
  sessions: AgentSession[];
  pendingInterventionsCount: number;
  onSeedScenario: () => void;
  seeding: boolean;
}

export const Header: React.FC<HeaderProps> = ({
  wsConnected,
  sessions,
  pendingInterventionsCount,
  onSeedScenario,
  seeding,
}) => {
  const activeCount = sessions.filter((s) => s.status === "RUNNING").length;
  const trippedCount = sessions.filter(
    (s) => s.status === "TRIPPED_LOOP" || s.status === "TRIPPED_BUDGET"
  ).length;
  const totalCost = sessions.reduce((acc, s) => acc + s.accumulated_cost_usd, 0);

  return (
    <header className="border-b border-[#222222] bg-[#000000] px-6 py-3">
      <div className="flex flex-wrap items-center justify-between gap-4">
        {/* Title and Identity */}
        <div className="flex items-center space-x-3">
          <div className="flex h-8 w-8 items-center justify-center border border-[#00ff66] bg-[#001105]">
            <Radio className="h-4 w-4 text-[#00ff66]" />
          </div>
          <div>
            <div className="flex items-center space-x-2">
              <span className="text-sm font-bold tracking-widest text-[#00ff66]">
                [ ARGUS // C2 CONSOLE ]
              </span>
              <span className="text-xs text-[#666666]">v0.1.0-STARK</span>
            </div>
            <div className="text-[10px] text-[#888888]">
              ZERO-TOLERANCE AGENT GOVERNANCE & OBSERVABILITY
            </div>
          </div>
        </div>

        {/* Fleet Metrics Strip */}
        <div className="flex flex-wrap items-center gap-3 text-xs font-mono">
          <button
            onClick={onSeedScenario}
            disabled={seeding}
            className="flex items-center space-x-1.5 border border-[#00e5ff] bg-[#00151a] px-3 py-1.5 text-[#00e5ff] hover:bg-[#00e5ff] hover:text-black font-bold transition-colors cursor-pointer disabled:opacity-50"
          >
            <Sparkles className="h-3.5 w-3.5" />
            <span>{seeding ? "SEEDING..." : "SEED LIVE SCENARIO"}</span>
          </button>

          <div className="flex items-center space-x-2 border border-[#222222] bg-[#050505] px-3 py-1.5">
            <Cpu className="h-3.5 w-3.5 text-[#00ff66]" />
            <span className="text-[#888888]">ACTIVE:</span>
            <span className="font-bold text-white">{activeCount}</span>
          </div>

          <div
            className={`flex items-center space-x-2 border px-3 py-1.5 ${
              trippedCount > 0
                ? "border-[#ff3333] bg-[#1a0000] text-[#ff3333] pulse-red"
                : "border-[#222222] bg-[#050505] text-[#888888]"
            }`}
          >
            <ShieldAlert className="h-3.5 w-3.5" />
            <span>TRIPPED:</span>
            <span className="font-bold">{trippedCount}</span>
          </div>

          <div
            className={`flex items-center space-x-2 border px-3 py-1.5 ${
              pendingInterventionsCount > 0
                ? "border-[#ffb000] bg-[#1a1200] text-[#ffb000]"
                : "border-[#222222] bg-[#050505] text-[#888888]"
            }`}
          >
            <Activity className="h-3.5 w-3.5" />
            <span>INTERVENTIONS:</span>
            <span className="font-bold">{pendingInterventionsCount}</span>
          </div>

          <div className="flex items-center space-x-2 border border-[#222222] bg-[#050505] px-3 py-1.5">
            <DollarSign className="h-3.5 w-3.5 text-[#00ff66]" />
            <span className="text-[#888888]">SPEND:</span>
            <span className="font-bold text-white">${totalCost.toFixed(4)}</span>
          </div>

          {/* WebSocket Status Indicator */}
          <div
            className={`flex items-center space-x-1.5 border px-3 py-1.5 ${
              wsConnected
                ? "border-[#00ff66] bg-[#001105] text-[#00ff66]"
                : "border-[#ff3333] bg-[#110000] text-[#ff3333]"
            }`}
          >
            <div
              className={`h-2 w-2 rounded-full ${
                wsConnected ? "bg-[#00ff66] pulse-green" : "bg-[#ff3333]"
              }`}
            />
            <span className="font-bold">{wsConnected ? "STREAM ONLINE" : "STREAM DISCONNECTED"}</span>
          </div>
        </div>
      </div>
    </header>
  );
};
