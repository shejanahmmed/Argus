import React, { useState, useMemo } from "react";
import { Play, Pause, XOctagon, Bot, Plus, Search, X, Unlock } from "lucide-react";
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
  { pill: string; label: string; bar: string; dot: string }
> = {
  RUNNING: {
    pill: "bg-emerald-500/10 text-emerald-400 border-emerald-500/20",
    label: "Running",
    bar: "bg-emerald-500",
    dot: "bg-emerald-400",
  },
  PAUSED_C2: {
    pill: "bg-amber-500/10 text-amber-400 border-amber-500/20",
    label: "Paused for C2",
    bar: "bg-amber-400",
    dot: "bg-amber-400",
  },
  TRIPPED_LOOP: {
    pill: "bg-rose-500/10 text-rose-400 border-rose-500/20",
    label: "Loop Tripped",
    bar: "bg-rose-500",
    dot: "bg-rose-500",
  },
  TRIPPED_BUDGET: {
    pill: "bg-rose-500/10 text-rose-400 border-rose-500/20",
    label: "Budget Exceeded",
    bar: "bg-rose-500",
    dot: "bg-rose-500",
  },
  COMPLETED: {
    pill: "bg-sky-500/10 text-sky-400 border-sky-500/20",
    label: "Completed",
    bar: "bg-sky-500",
    dot: "bg-sky-400",
  },
  TERMINATED: {
    pill: "bg-zinc-800 text-zinc-400 border-zinc-700",
    label: "Terminated",
    bar: "bg-zinc-600",
    dot: "bg-zinc-500",
  },
};

type FilterCategory = "ALL" | "RUNNING" | "PAUSED" | "TRIPPED";

export const FleetOverview: React.FC<FleetOverviewProps> = ({
  sessions,
  selectedSessionId,
  onSelectSession,
  onPause,
  onResume,
  onTerminate,
  onSeedScenario,
}) => {
  const [searchQuery, setSearchQuery] = useState<string>("");
  const [statusFilter, setStatusFilter] = useState<FilterCategory>("ALL");

  const runningCount = sessions.filter((s) => s.status === "RUNNING").length;
  const pausedCount = sessions.filter((s) => s.status === "PAUSED_C2").length;
  const trippedCount = sessions.filter((s) => s.status.startsWith("TRIPPED_")).length;

  const filteredSessions = useMemo(() => {
    return sessions.filter((s) => {
      // Status filter
      if (statusFilter === "RUNNING" && s.status !== "RUNNING") return false;
      if (statusFilter === "PAUSED" && s.status !== "PAUSED_C2") return false;
      if (statusFilter === "TRIPPED" && !s.status.startsWith("TRIPPED_")) return false;

      // Text search
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase().trim();
        const nameMatch = s.agent_name.toLowerCase().includes(q);
        const idMatch = s.session_id.toLowerCase().includes(q);
        const fwMatch = s.framework.toLowerCase().includes(q);
        if (!nameMatch && !idMatch && !fwMatch) return false;
      }
      return true;
    });
  }, [sessions, statusFilter, searchQuery]);

  return (
    <div className="rounded-xl border border-[#222228] bg-[#111114] flex flex-col shadow-sm overflow-hidden">
      {/* Panel Header */}
      <div className="flex flex-wrap items-center justify-between px-4 py-3 border-b border-[#222228] bg-[#0d0d10] gap-2">
        <div className="flex items-center gap-2.5">
          <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-[#18181b] border border-[#27272a] text-zinc-300">
            <Bot className="h-3.5 w-3.5 text-zinc-400" />
          </div>
          <div className="flex items-center gap-2">
            <h2 className="text-xs font-semibold text-zinc-100 uppercase tracking-wider whitespace-nowrap">
              Agent Fleet
            </h2>
            <span className="rounded-md bg-[#18181b] px-2 py-0.5 text-[10px] font-mono font-medium text-zinc-400 border border-[#27272a] whitespace-nowrap shrink-0">
              {sessions.length}
            </span>
            {runningCount > 0 && (
              <span className="flex items-center gap-1 text-[10px] text-emerald-400 font-mono whitespace-nowrap shrink-0">
                <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-pulse" />
                {runningCount} live
              </span>
            )}
          </div>
        </div>
      </div>

      {/* Search & Filter Toolbar */}
      <div className="px-4 py-2.5 border-b border-[#1f1f26] bg-[#0f0f13] flex flex-col gap-2">
        {/* Search Input */}
        <div className="relative w-full">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-zinc-500" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search by agent name, framework, or ID..."
            className="w-full rounded-md border border-[#27272a] bg-[#141418] pl-8 pr-7 py-1 text-xs text-zinc-200 placeholder-zinc-500 focus:border-zinc-500 focus:outline-hidden transition-colors"
          />
          {searchQuery && (
            <button
              onClick={() => setSearchQuery("")}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-zinc-500 hover:text-zinc-300 p-0.5 rounded cursor-pointer"
            >
              <X className="h-3 w-3" />
            </button>
          )}
        </div>

        {/* Filter Pills */}
        <div className="flex items-center gap-1 shrink-0 overflow-x-auto w-full pb-0.5">
          {(
            [
              { id: "ALL", label: `All (${sessions.length})` },
              { id: "RUNNING", label: `Running (${runningCount})` },
              { id: "PAUSED", label: `Paused (${pausedCount})` },
              { id: "TRIPPED", label: `Tripped (${trippedCount})` },
            ] as const
          ).map((tab) => {
            const isActive = statusFilter === tab.id;
            return (
              <button
                key={tab.id}
                onClick={() => setStatusFilter(tab.id)}
                className={`px-2 py-0.5 rounded-md text-[11px] font-medium transition-colors cursor-pointer whitespace-nowrap shrink-0 ${
                  isActive
                    ? "bg-[#222228] text-white border border-zinc-600/80 shadow-2xs"
                    : "text-zinc-500 hover:text-zinc-300 hover:bg-[#141418]"
                }`}
              >
                {tab.label}
              </button>
            );
          })}
        </div>
      </div>

      {/* Fleet Session List */}
      <div className="p-3 space-y-2 max-h-[480px] overflow-y-auto">
        {sessions.length === 0 ? (
          <div className="rounded-lg border border-dashed border-[#27272a] bg-[#141418]/50 p-8 text-center">
            <div className="mx-auto mb-3 flex h-8 w-8 items-center justify-center rounded-md bg-[#18181b] border border-[#27272a] text-zinc-400">
              <Bot className="h-4 w-4" />
            </div>
            <p className="text-xs font-medium text-zinc-300 mb-1">No active agent sessions</p>
            <p className="text-[11px] text-zinc-500 mb-4 max-w-xs mx-auto">
              Initialize a scenario from the Simulation toolkit or connect an external agent runtime
              via the Argus SDK.
            </p>
            {onSeedScenario && (
              <button
                onClick={onSeedScenario}
                className="inline-flex items-center gap-1.5 rounded-md bg-white hover:bg-zinc-200 text-zinc-950 px-3 py-1.5 text-xs font-semibold shadow-xs transition-all cursor-pointer"
              >
                <Plus className="h-3.5 w-3.5" />
                <span>Seed Scenario</span>
              </button>
            )}
          </div>
        ) : filteredSessions.length === 0 ? (
          <div className="rounded-lg border border-dashed border-[#222228] bg-[#141418]/30 p-6 text-center text-xs text-zinc-500">
            No agent sessions match &ldquo;{searchQuery || statusFilter}&rdquo;.
          </div>
        ) : (
          filteredSessions.map((sess) => {
            const isSelected = sess.session_id === selectedSessionId;
            const status = statusConfig[sess.status] || statusConfig.RUNNING;
            const burnPct = Math.min(
              100,
              Math.max(2, (sess.accumulated_cost_usd / Math.max(0.01, sess.budget_cap_usd)) * 100)
            );

            const isRunning = sess.status === "RUNNING";
            const isPaused = sess.status === "PAUSED_C2";
            const isTripped = sess.status.startsWith("TRIPPED_");

            const railColor = isRunning
              ? "border-l-emerald-500"
              : isPaused
              ? "border-l-amber-400"
              : isTripped
              ? "border-l-rose-500"
              : sess.status === "COMPLETED"
              ? "border-l-sky-500"
              : "border-l-zinc-600";

            return (
              <div
                key={sess.session_id}
                onClick={() => onSelectSession(sess.session_id)}
                className={`rounded-lg border p-3 transition-all cursor-pointer border-l-[3px] ${railColor} ${
                  isSelected
                    ? "border-zinc-500/80 bg-[#17171e] shadow-sm ring-1 ring-zinc-600/40"
                    : "border-[#222228] bg-[#131317] hover:border-[#2e2e38] hover:bg-[#16161c]"
                }`}
              >
                {/* Header: Agent Identity & Status Pill */}
                <div className="flex items-start justify-between gap-2 mb-2">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-medium text-white truncate">
                        {sess.agent_name}
                      </span>
                      <span className="rounded-md bg-[#1a1a20] px-1.5 py-0.5 text-[9px] font-mono font-medium text-zinc-400 border border-[#27272a] uppercase whitespace-nowrap shrink-0">
                        {sess.framework}
                      </span>
                    </div>
                    <div className="text-[10px] text-zinc-500 font-mono mt-0.5 flex flex-wrap items-center gap-2">
                      <span className="whitespace-nowrap">id: {sess.session_id.substring(0, 8)}</span>
                      {sess.latest_checkpoint_id && (
                        <>
                          <span className="text-zinc-700">•</span>
                          <span className="whitespace-nowrap">cp: {sess.latest_checkpoint_id.substring(0, 8)}</span>
                        </>
                      )}
                    </div>
                  </div>

                  <span
                    className={`inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-[10px] font-mono font-medium border shrink-0 whitespace-nowrap ${status.pill}`}
                  >
                    <span className={`h-1.5 w-1.5 rounded-full ${status.dot} shrink-0`} />
                    {status.label}
                  </span>
                </div>

                {/* Footer: Spend Budget Track & C2 Quick Actions */}
                <div className="flex items-center justify-between gap-3 pt-2 border-t border-[#1f1f26]">
                  {/* Budget Burn Track */}
                  <div className="flex-1 min-w-0">
                    <div className="flex justify-between text-[10px] text-zinc-400 mb-1 font-mono gap-1">
                      <span className="text-zinc-300 whitespace-nowrap">${sess.accumulated_cost_usd.toFixed(4)}</span>
                      <span className="text-zinc-500 whitespace-nowrap">
                        cap ${sess.budget_cap_usd.toFixed(2)} ({burnPct.toFixed(0)}%)
                      </span>
                    </div>
                    <div className="h-1 w-full rounded-full bg-[#1e1e24] overflow-hidden">
                      <div
                        className={`h-full rounded-full ${status.bar} transition-all duration-300`}
                        style={{ width: `${burnPct}%` }}
                      />
                    </div>
                  </div>

                  {/* Contextual Action Buttons */}
                  <div className="flex items-center gap-1.5 shrink-0" onClick={(e) => e.stopPropagation()}>
                    {isRunning && (
                      <button
                        title="Pause session for inspection / C2 intervention"
                        onClick={() => onPause(sess.session_id)}
                        className="rounded-md px-2 py-0.5 border border-[#27272a] bg-[#18181b] hover:bg-[#222228] text-zinc-300 text-[11px] font-medium transition-colors cursor-pointer flex items-center gap-1 whitespace-nowrap shrink-0"
                      >
                        <Pause className="h-3 w-3 text-amber-400 shrink-0" />
                        <span>Pause</span>
                      </button>
                    )}

                    {isTripped && (
                      <button
                        title="Unlock C2: Move session to PAUSED_C2 to inspect state, edit memory, or adjust budget"
                        onClick={() => onPause(sess.session_id)}
                        className="rounded-md px-2 py-0.5 border border-amber-500/40 bg-amber-500/10 hover:bg-amber-500/20 text-amber-300 text-[11px] font-medium transition-colors cursor-pointer flex items-center gap-1 whitespace-nowrap shrink-0"
                      >
                        <Unlock className="h-3 w-3 text-amber-400 shrink-0" />
                        <span>Unlock C2</span>
                      </button>
                    )}

                    {isPaused && (
                      <button
                        title="Resume agent execution"
                        onClick={() => onResume(sess.session_id)}
                        className="rounded-md px-2 py-0.5 border border-emerald-500/30 bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-400 text-[11px] font-medium transition-colors cursor-pointer flex items-center gap-1 whitespace-nowrap shrink-0"
                      >
                        <Play className="h-3 w-3 text-emerald-400 shrink-0" />
                        <span>Resume</span>
                      </button>
                    )}

                    {sess.status !== "TERMINATED" && sess.status !== "COMPLETED" && (
                      <button
                        title="Terminate session immediately"
                        onClick={() => onTerminate(sess.session_id)}
                        className="rounded-md p-1 text-zinc-500 hover:text-rose-400 hover:bg-rose-500/10 transition-colors cursor-pointer border border-transparent hover:border-rose-500/20 shrink-0"
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
