import React from "react";
import { Play, Pause, XOctagon, Bot, Plus } from "lucide-react";
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

const statusConfig: Record<
  SessionStatus,
  { pill: string; label: string; bar: string }
> = {
  RUNNING: {
    pill: "bg-emerald-500/10 text-emerald-400 border-emerald-500/20",
    label: "Running",
    bar: "bg-emerald-500",
  },
  PAUSED_C2: {
    pill: "bg-amber-500/10 text-amber-400 border-amber-500/20",
    label: "Paused for C2",
    bar: "bg-amber-400",
  },
  TRIPPED_LOOP: {
    pill: "bg-rose-500/10 text-rose-400 border-rose-500/20",
    label: "Loop Tripped",
    bar: "bg-rose-500",
  },
  TRIPPED_BUDGET: {
    pill: "bg-rose-500/10 text-rose-400 border-rose-500/20",
    label: "Budget Exceeded",
    bar: "bg-rose-500",
  },
  COMPLETED: {
    pill: "bg-sky-500/10 text-sky-400 border-sky-500/20",
    label: "Completed",
    bar: "bg-sky-500",
  },
  TERMINATED: {
    pill: "bg-zinc-800 text-zinc-400 border-zinc-700",
    label: "Terminated",
    bar: "bg-zinc-600",
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
    <div className="rounded-xl border border-zinc-800 bg-[#121215] flex flex-col shadow-sm">
      {/* Card Header */}
      <div className="flex items-center justify-between px-5 py-4 border-b border-zinc-800">
        <div className="flex items-center gap-2.5">
          <Bot className="h-4 w-4 text-zinc-400" />
          <h2 className="text-sm font-semibold text-zinc-100">Agent Fleet</h2>
          <span className="rounded-full bg-zinc-800 px-2 py-0.5 text-xs font-medium text-zinc-400 border border-zinc-700/60">
            {sessions.length}
          </span>
        </div>
        <span className="text-xs text-zinc-500">Autonomous Runtimes</span>
      </div>

      {/* Fleet Items */}
      <div className="p-4 space-y-2.5 max-h-[460px] overflow-y-auto">
        {sessions.length === 0 ? (
          <div className="rounded-lg border border-dashed border-zinc-800 bg-zinc-900/40 p-8 text-center">
            <p className="text-sm font-medium text-zinc-300 mb-1">No active agent sessions</p>
            <p className="text-xs text-zinc-500 mb-4">
              Seed a multi-agent scenario to monitor loops, MCP tool calls, and FinOps metrics.
            </p>
            {onSeedScenario && (
              <button
                onClick={onSeedScenario}
                className="inline-flex items-center gap-1.5 rounded-md bg-zinc-100 hover:bg-white text-zinc-950 px-3 py-1.5 text-xs font-medium transition-colors cursor-pointer"
              >
                <Plus className="h-3.5 w-3.5" />
                <span>Initialize Scenario</span>
              </button>
            )}
          </div>
        ) : (
          sessions.map((sess) => {
            const isSelected = sess.session_id === selectedSessionId;
            const status = statusConfig[sess.status] || statusConfig.RUNNING;
            const burnPct = Math.min(
              100,
              Math.max(2, (sess.accumulated_cost_usd / Math.max(0.01, sess.budget_cap_usd)) * 100)
            );

            return (
              <div
                key={sess.session_id}
                onClick={() => onSelectSession(sess.session_id)}
                className={`rounded-lg border p-3.5 transition-all cursor-pointer ${
                  isSelected
                    ? "border-zinc-500 bg-zinc-800/60 shadow-sm"
                    : "border-zinc-800 bg-zinc-900/40 hover:border-zinc-700 hover:bg-zinc-900/80"
                }`}
              >
                {/* Title & Status */}
                <div className="flex items-start justify-between gap-2 mb-2">
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium text-white">{sess.agent_name}</span>
                      <span className="rounded bg-zinc-800 px-1.5 py-0.5 text-[10px] font-medium text-zinc-400 border border-zinc-700/60 uppercase">
                        {sess.framework}
                      </span>
                    </div>
                    <div className="text-[11px] text-zinc-500 font-mono mt-0.5">
                      id: {sess.session_id.substring(0, 8)}...
                    </div>
                  </div>

                  <span
                    className={`inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium border ${status.pill}`}
                  >
                    {status.label}
                  </span>
                </div>

                {/* Spend & Controls */}
                <div className="flex items-center justify-between gap-4 pt-2.5 border-t border-zinc-800/80">
                  <div className="flex-1">
                    <div className="flex justify-between text-[11px] text-zinc-400 mb-1 font-mono">
                      <span>${sess.accumulated_cost_usd.toFixed(4)}</span>
                      <span className="text-zinc-500">cap ${sess.budget_cap_usd.toFixed(2)}</span>
                    </div>
                    <div className="h-1.5 w-full rounded-full bg-zinc-800 overflow-hidden">
                      <div
                        className={`h-full rounded-full ${status.bar} transition-all duration-300`}
                        style={{ width: `${burnPct}%` }}
                      />
                    </div>
                  </div>

                  <div className="flex items-center gap-1.5" onClick={(e) => e.stopPropagation()}>
                    {(sess.status === "RUNNING" || sess.status === "TRIPPED_LOOP") && (
                      <button
                        title="Pause session for inspection / C2 intervention"
                        onClick={() => onPause(sess.session_id)}
                        className="rounded px-2 py-1 border border-zinc-700 hover:bg-zinc-800 text-zinc-300 text-xs font-medium transition-colors cursor-pointer flex items-center gap-1"
                      >
                        <Pause className="h-3 w-3 text-amber-400" />
                        <span>{sess.status === "TRIPPED_LOOP" ? "Unlock C2" : "Pause"}</span>
                      </button>
                    )}

                    {sess.status === "PAUSED_C2" && (
                      <button
                        title="Resume agent execution"
                        onClick={() => onResume(sess.session_id)}
                        className="rounded px-2.5 py-1 border border-emerald-500/30 bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-400 text-xs font-medium transition-colors cursor-pointer flex items-center gap-1"
                      >
                        <Play className="h-3 w-3" />
                        <span>Resume</span>
                      </button>
                    )}

                    {sess.status !== "TERMINATED" && sess.status !== "COMPLETED" && (
                      <button
                        title="Terminate session immediately"
                        onClick={() => onTerminate(sess.session_id)}
                        className="rounded p-1 text-zinc-500 hover:text-rose-400 hover:bg-rose-500/10 transition-colors cursor-pointer"
                      >
                        <XOctagon className="h-3.5 w-3.5" />
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
