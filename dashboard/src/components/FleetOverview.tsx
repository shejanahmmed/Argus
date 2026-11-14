import React from "react";
import { Play, Pause, XOctagon, Eye } from "lucide-react";
import { AgentSession, SessionStatus } from "../types";

interface FleetOverviewProps {
  sessions: AgentSession[];
  selectedSessionId: string | null;
  onSelectSession: (sessionId: string) => void;
  onPause: (sessionId: string) => void;
  onResume: (sessionId: string) => void;
  onTerminate: (sessionId: string) => void;
}

const statusColors: Record<SessionStatus, string> = {
  RUNNING: "border-[#00ff66] text-[#00ff66] bg-[#001408]",
  PAUSED_C2: "border-[#ffb000] text-[#ffb000] bg-[#1a1200]",
  TRIPPED_LOOP: "border-[#ff3333] text-[#ff3333] bg-[#220000] pulse-red",
  TRIPPED_BUDGET: "border-[#ff3333] text-[#ff3333] bg-[#220000]",
  COMPLETED: "border-[#00e5ff] text-[#00e5ff] bg-[#001a1f]",
  TERMINATED: "border-[#555555] text-[#777777] bg-[#111111]",
};

export const FleetOverview: React.FC<FleetOverviewProps> = ({
  sessions,
  selectedSessionId,
  onSelectSession,
  onPause,
  onResume,
  onTerminate,
}) => {
  return (
    <div className="terminal-card flex flex-col h-full">
      <div className="dot-matrix-header flex items-center justify-between px-4 py-2 text-xs">
        <span className="text-[#00ff66]">[ 01 // AGENT FLEET STATE MATRIX ]</span>
        <span className="text-[#666666]">TOTAL UNITS: {sessions.length}</span>
      </div>

      <div className="overflow-x-auto flex-1 p-2">
        <table className="w-full text-left font-mono text-xs border-collapse">
          <thead>
            <tr className="border-b border-[#222222] text-[#777777] text-[11px]">
              <th className="py-2 px-3">SESSION ID</th>
              <th className="py-2 px-3">AGENT NAME</th>
              <th className="py-2 px-3">FRAMEWORK</th>
              <th className="py-2 px-3">STATE</th>
              <th className="py-2 px-3">SPEND / CAP</th>
              <th className="py-2 px-3 text-right">C2 CONTROLS</th>
            </tr>
          </thead>
          <tbody>
            {sessions.length === 0 ? (
              <tr>
                <td colSpan={6} className="py-8 text-center text-[#555555]">
                  NO ACTIVE AGENT SESSIONS REGISTERED
                </td>
              </tr>
            ) : (
              sessions.map((sess) => {
                const isSelected = sess.session_id === selectedSessionId;
                return (
                  <tr
                    key={sess.session_id}
                    onClick={() => onSelectSession(sess.session_id)}
                    className={`cursor-pointer border-b border-[#181818] transition-colors ${
                      isSelected ? "bg-[#111111] border-l-2 border-l-[#00ff66]" : "hover:bg-[#080808]"
                    }`}
                  >
                    <td className="py-2.5 px-3 font-semibold text-white">
                      {sess.session_id.substring(0, 8)}...
                    </td>
                    <td className="py-2.5 px-3 text-[#cccccc]">{sess.agent_name}</td>
                    <td className="py-2.5 px-3 uppercase text-[#888888]">{sess.framework}</td>
                    <td className="py-2.5 px-3">
                      <span className={`status-badge ${statusColors[sess.status]}`}>
                        {sess.status}
                      </span>
                    </td>
                    <td className="py-2.5 px-3">
                      <span className="text-white">${sess.accumulated_cost_usd.toFixed(4)}</span>
                      <span className="text-[#666666]"> / ${sess.budget_cap_usd.toFixed(2)}</span>
                    </td>
                    <td className="py-2.5 px-3 text-right space-x-1" onClick={(e) => e.stopPropagation()}>
                      <button
                        title="Inspect Topology"
                        onClick={() => onSelectSession(sess.session_id)}
                        className="p-1 border border-[#333333] hover:border-[#00ff66] text-[#aaaaaa] hover:text-[#00ff66] transition-colors"
                      >
                        <Eye className="h-3.5 w-3.5" />
                      </button>

                      {sess.status === "RUNNING" && (
                        <button
                          title="Pause Session"
                          onClick={() => onPause(sess.session_id)}
                          className="p-1 border border-[#333333] hover:border-[#ffb000] text-[#aaaaaa] hover:text-[#ffb000] transition-colors"
                        >
                          <Pause className="h-3.5 w-3.5" />
                        </button>
                      )}

                      {(sess.status === "PAUSED_C2" || sess.status === "TRIPPED_LOOP") && (
                        <button
                          title="Resume Session"
                          onClick={() => onResume(sess.session_id)}
                          className="p-1 border border-[#333333] hover:border-[#00ff66] text-[#aaaaaa] hover:text-[#00ff66] transition-colors"
                        >
                          <Play className="h-3.5 w-3.5" />
                        </button>
                      )}

                      {sess.status !== "TERMINATED" && (
                        <button
                          title="Force Kill (Terminate)"
                          onClick={() => onTerminate(sess.session_id)}
                          className="p-1 border border-[#333333] hover:border-[#ff3333] text-[#aaaaaa] hover:text-[#ff3333] transition-colors"
                        >
                          <XOctagon className="h-3.5 w-3.5" />
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
};
