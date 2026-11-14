import React from "react";
import { Play, Pause, XOctagon, Cpu, Sparkles, CheckCircle2 } from "lucide-react";
import { AgentSession, SessionStatus } from "../types";

interface FleetOverviewProps {
  sessions: AgentSession[];
  selectedSessionId: string | null;
  onSelectSession: (sessionId: string) => void;
  onPause: (sessionId: string) => void;
  onResume: (sessionId: string) => void;
  onTerminate: (sessionId: string) => void;
  onSeedScenario?: () => void;
}

const statusStyles: Record<
  SessionStatus,
  { badge: string; dot: string; bar: string; label: string }
> = {
  RUNNING: {
    badge: "border-[#00ff66] text-[#00ff66] bg-[#001808]",
    dot: "bg-[#00ff66] pulse-green",
    bar: "bg-[#00ff66]",
    label: "RUNNING",
  },
  PAUSED_C2: {
    badge: "border-[#ffb000] text-[#ffb000] bg-[#1f1300]",
    dot: "bg-[#ffb000]",
    bar: "bg-[#ffb000]",
    label: "PAUSED // C2 GATE",
  },
  TRIPPED_LOOP: {
    badge: "border-[#ff3333] text-[#ff3333] bg-[#240303] pulse-red",
    dot: "bg-[#ff3333]",
    bar: "bg-[#ff3333]",
    label: "TRIPPED // LOOP",
  },
  TRIPPED_BUDGET: {
    badge: "border-[#ff3333] text-[#ff3333] bg-[#240303] pulse-red",
    dot: "bg-[#ff3333]",
    bar: "bg-[#ff3333]",
    label: "TRIPPED // BUDGET",
  },
  COMPLETED: {
    badge: "border-[#00e5ff] text-[#00e5ff] bg-[#001a22]",
    dot: "bg-[#00e5ff]",
    bar: "bg-[#00e5ff]",
    label: "COMPLETED",
  },
  TERMINATED: {
    badge: "border-[#525252] text-[#888888] bg-[#121212]",
    dot: "bg-[#666666]",
    bar: "bg-[#525252]",
    label: "TERMINATED",
  },
};

export const FleetOverview: React.FC<FleetOverviewProps> = ({
  sessions,
  selectedSessionId,
  onSelectSession,
  onPause,
  onResume,
  onTerminate,
  onSeedScenario,
}) => {
  return (
    <div className="terminal-card flex flex-col">
      <div className="dot-matrix-header flex items-center justify-between px-4 py-3 text-xs">
        <div className="flex items-center gap-2">
          <Cpu className="h-4 w-4 text-[#00ff66]" />
          <span className="text-[#00ff66]">[ 01 // AGENT FLEET STATE MATRIX ]</span>
        </div>
        <span className="border border-[#262626] bg-[#0a0a0a] px-2 py-0.5 text-[10px] text-[#a3a3a3]">
          UNITS TRACKED: {sessions.length}
        </span>
      </div>

      <div className="p-3.5 space-y-3 max-h-[430px] overflow-y-auto">
        {sessions.length === 0 ? (
          <div className="border border-dashed border-[#262626] bg-[#060606] p-8 text-center">
            <div className="text-xs font-bold text-[#a3a3a3] mb-2">
              NO AUTONOMOUS AGENT UNITS ACTIVE IN WORKSPACE
            </div>
            <div className="text-[11px] text-[#666666] mb-4">
              Initialize the multi-agent telemetry scenario to inspect LangGraph loops, CrewAI MCP gates, and AutoGPT FinOps traces.
            </div>
            {onSeedScenario && (
              <button
                onClick={onSeedScenario}
                className="inline-flex items-center gap-2 border border-[#00ff66] bg-[#001a09] px-4 py-2 text-xs font-bold text-[#00ff66] hover:bg-[#00ff66] hover:text-black transition-all cursor-pointer"
              >
                <Sparkles className="h-3.5 w-3.5" />
                <span>INITIALIZE MULTI-AGENT DEMO FLEET</span>
              </button>
            )}
          </div>
        ) : (
          sessions.map((sess) => {
            const isSelected = sess.session_id === selectedSessionId;
            const st = statusStyles[sess.status] || statusStyles.RUNNING;
            const burnPct = Math.min(
              100,
              Math.max(2, (sess.accumulated_cost_usd / Math.max(0.01, sess.budget_cap_usd)) * 100)
            );

            return (
              <div
                key={sess.session_id}
                onClick={() => onSelectSession(sess.session_id)}
                className={`border p-3.5 transition-all cursor-pointer ${
                  isSelected
                    ? "border-[#00ff66] bg-[#0b120d] shadow-[inset_3px_0_0_#00ff66]"
                    : "border-[#1f1f1f] bg-[#060606] hover:border-[#383838] hover:bg-[#0a0a0a]"
                }`}
              >
                {/* Row 1: Agent Identity & Status Badge */}
                <div className="flex flex-wrap items-start justify-between gap-2 mb-2.5">
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-bold text-white tracking-wide">
                        {sess.agent_name}
                      </span>
                      {isSelected && (
                        <span className="inline-flex items-center gap-1 bg-[#00ff66] text-black px-1.5 py-0.2 text-[9px] font-bold">
                          <CheckCircle2 className="h-2.5 w-2.5" />
                          ACTIVE TARGET
                        </span>
                      )}
                    </div>
                    <div className="flex items-center gap-2 mt-1 text-[10px] text-[#737373]">
                      <span className="border border-[#262626] bg-[#0f0f0f] px-1.5 py-0.5 uppercase font-bold text-[#a3a3a3]">
                        {sess.framework}
                      </span>
                      <span>WF: {sess.workflow_id}</span>
                      <span>•</span>
                      <span>ID: {sess.session_id.substring(0, 12)}</span>
                    </div>
                  </div>

                  <span className={`status-badge ${st.badge}`}>
                    <span className={`h-1.5 w-1.5 rounded-full ${st.dot}`} />
                    {st.label}
                  </span>
                </div>

                {/* Row 2: Budget Utilization Gauge & C2 Controls */}
                <div className="flex flex-wrap items-end justify-between gap-3 pt-2 border-t border-[#171717]">
                  <div className="flex-1 min-w-[160px]">
                    <div className="flex justify-between text-[10px] mb-1">
                      <span className="text-[#737373]">BUDGET UTILIZATION</span>
                      <span>
                        <span className="font-bold text-white">
                          ${sess.accumulated_cost_usd.toFixed(4)}
                        </span>
                        <span className="text-[#666666]"> / ${sess.budget_cap_usd.toFixed(2)}</span>
                      </span>
                    </div>
                    <div className="h-1.5 w-full bg-[#141414] overflow-hidden">
                      <div
                        className={`h-full ${st.bar} transition-all duration-300`}
                        style={{ width: `${burnPct}%` }}
                      />
                    </div>
                  </div>

                  <div
                    className="flex items-center gap-1.5"
                    onClick={(e) => e.stopPropagation()}
                  >
                    {(sess.status === "RUNNING" || sess.status === "TRIPPED_LOOP") && (
                      <button
                        title="Transition session to PAUSED_C2 for memory patching or inspection"
                        onClick={() => onPause(sess.session_id)}
                        className="flex items-center gap-1 px-2.5 py-1 border border-[#ffb000]/70 bg-[#1a1000] text-[#ffb000] hover:bg-[#ffb000] hover:text-black text-[10px] font-bold transition-colors cursor-pointer"
                      >
                        <Pause className="h-3 w-3" />
                        <span>{sess.status === "TRIPPED_LOOP" ? "UNLOCK C2" : "PAUSE C2"}</span>
                      </button>
                    )}

                    {sess.status === "PAUSED_C2" && (
                      <button
                        title="Resume execution and reset loop detector window"
                        onClick={() => onResume(sess.session_id)}
                        className="flex items-center gap-1 px-2.5 py-1 border border-[#00ff66]/70 bg-[#001808] text-[#00ff66] hover:bg-[#00ff66] hover:text-black text-[10px] font-bold transition-colors cursor-pointer"
                      >
                        <Play className="h-3 w-3" />
                        <span>RESUME</span>
                      </button>
                    )}

                    {sess.status !== "TERMINATED" && sess.status !== "COMPLETED" && (
                      <button
                        title="Execute hard kill-switch (TERMINATED)"
                        onClick={() => onTerminate(sess.session_id)}
                        className="flex items-center gap-1 px-2.5 py-1 border border-[#ff3333]/70 bg-[#1f0303] text-[#ff4444] hover:bg-[#ff3333] hover:text-black text-[10px] font-bold transition-colors cursor-pointer"
                      >
                        <XOctagon className="h-3 w-3" />
                        <span>KILL</span>
                      </button>
                    )}
                  </div>
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
};
