import React, { useState, useMemo } from "react";
import { Terminal, AlertTriangle, Link2 } from "lucide-react";
import { ContainerLog } from "../types";

interface LogWaterfallProps {
  logs: ContainerLog[];
}

interface ParsedLogContent {
  cleanMessage: string;
  level: string;
}

function parseRawLogMessage(raw: string, fallbackSeverity: string): ParsedLogContent {
  try {
    const parsed = JSON.parse(raw);
    if (typeof parsed === "object" && parsed !== null) {
      return {
        cleanMessage: String(parsed.msg || parsed.message || raw),
        level: String(parsed.level || fallbackSeverity || "INFO").toUpperCase(),
      };
    }
  } catch {
    // Plaintext line
  }
  return { cleanMessage: raw, level: (fallbackSeverity || "INFO").toUpperCase() };
}

export const LogWaterfall: React.FC<LogWaterfallProps> = ({ logs }) => {
  const [filter, setFilter] = useState<"ALL" | "ANOMALIES" | "CORRELATED">("ALL");
  const [searchQuery, setSearchQuery] = useState<string>("");

  const filteredLogs = useMemo(() => {
    return logs.filter((log) => {
      if (filter === "ANOMALIES") {
        if (!log.is_container_anomaly && log.severity !== "ERROR") return false;
      }
      if (filter === "CORRELATED") {
        if (!log.trace_id && !log.session_id) return false;
      }
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase();
        const matchesMsg = log.message.toLowerCase().includes(q);
        const matchesStream = log.log_stream.toLowerCase().includes(q);
        const matchesAnomaly = log.anomaly_type ? log.anomaly_type.toLowerCase().includes(q) : false;
        if (!matchesMsg && !matchesStream && !matchesAnomaly) return false;
      }
      return true;
    });
  }, [logs, filter, searchQuery]);

  return (
    <div className="rounded-xl border border-zinc-800 bg-[#121215] flex flex-col shadow-sm">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between px-5 py-4 border-b border-zinc-800 gap-3">
        <div className="flex items-center gap-2.5">
          <Terminal className="h-4 w-4 text-zinc-400" />
          <h2 className="text-sm font-semibold text-zinc-100">Container Log Stream</h2>
        </div>

        <div className="flex items-center gap-2 flex-wrap">
          <input
            type="text"
            placeholder="Filter logs or streams..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="rounded bg-zinc-900 border border-zinc-800 px-2.5 py-1 text-xs text-zinc-200 placeholder-zinc-500 focus:outline-none focus:border-zinc-700 w-36 sm:w-48"
          />

          <div className="flex items-center rounded-lg bg-zinc-900 p-0.5 border border-zinc-800 text-xs">
            <button
              onClick={() => setFilter("ALL")}
              className={`rounded px-2.5 py-1 font-medium cursor-pointer transition-colors ${
                filter === "ALL"
                  ? "bg-zinc-800 text-white"
                  : "text-zinc-400 hover:text-zinc-200"
              }`}
            >
              All ({logs.length})
            </button>
            <button
              onClick={() => setFilter("ANOMALIES")}
              className={`rounded px-2.5 py-1 font-medium cursor-pointer transition-colors ${
                filter === "ANOMALIES"
                  ? "bg-zinc-800 text-white"
                  : "text-zinc-400 hover:text-zinc-200"
              }`}
            >
              Errors & OOM
            </button>
            <button
              onClick={() => setFilter("CORRELATED")}
              className={`rounded px-2.5 py-1 font-medium cursor-pointer transition-colors ${
                filter === "CORRELATED"
                  ? "bg-zinc-800 text-white"
                  : "text-zinc-400 hover:text-zinc-200"
              }`}
            >
              Trace Linked
            </button>
          </div>
        </div>
      </div>

      {/* Log List */}
      <div className="p-4 space-y-2 max-h-[300px] overflow-y-auto font-mono text-xs">
        {filteredLogs.length === 0 ? (
          <div className="rounded-lg border border-dashed border-zinc-800 bg-zinc-950/40 p-6 text-center text-zinc-500 font-sans">
            No container log entries matching current filter
          </div>
        ) : (
          filteredLogs.map((log) => {
            const { cleanMessage, level } = parseRawLogMessage(log.message, log.severity);
            const isError = level === "ERROR" || log.is_container_anomaly;
            const isWarn = level === "WARN" || level === "WARNING";
            const anomalyLabel = log.anomaly_type
              ? log.anomaly_type.replace(/_/g, " ")
              : log.is_container_anomaly
              ? "OOM Crash"
              : level;

            return (
              <div
                key={log.log_id}
                className={`rounded-lg border p-3 transition-colors ${
                  isError
                    ? "border-rose-500/30 bg-rose-500/5 text-rose-300"
                    : isWarn
                    ? "border-amber-500/30 bg-amber-500/5 text-amber-300"
                    : "border-zinc-800/80 bg-zinc-950 text-zinc-300"
                }`}
              >
                <div className="flex flex-wrap items-center justify-between gap-2 mb-1">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span
                      className={`rounded px-1.5 py-0.5 text-[10px] font-semibold border uppercase ${
                        isError
                          ? "border-rose-500/30 bg-rose-500/10 text-rose-400"
                          : isWarn
                          ? "border-amber-500/30 bg-amber-500/10 text-amber-400"
                          : "border-zinc-700 bg-zinc-800 text-zinc-300"
                      }`}
                    >
                      {anomalyLabel}
                    </span>
                    <span className="text-zinc-400 font-sans font-medium text-xs">
                      {log.log_stream}
                    </span>
                    <span className="text-[11px] text-zinc-500">
                      {new Date(log.timestamp).toLocaleTimeString()}
                    </span>
                  </div>

                  <div className="flex items-center gap-2">
                    {log.session_id && (
                      <span className="inline-flex items-center gap-1 rounded bg-zinc-900 border border-zinc-800 px-2 py-0.5 text-[11px] text-purple-400">
                        Sess: {log.session_id.substring(0, 8)}
                      </span>
                    )}
                    {log.trace_id && (
                      <span className="inline-flex items-center gap-1 rounded bg-zinc-900 border border-zinc-800 px-2 py-0.5 text-[11px] text-sky-400">
                        <Link2 className="h-3 w-3" />
                        Trace: {log.trace_id.substring(0, 8)}
                      </span>
                    )}
                  </div>
                </div>

                <div className="flex items-start gap-2 pt-0.5 leading-relaxed font-sans text-xs">
                  {isError && (
                    <AlertTriangle className="h-3.5 w-3.5 text-rose-400 shrink-0 mt-0.5" />
                  )}
                  <span className="break-words">{cleanMessage}</span>
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
};
