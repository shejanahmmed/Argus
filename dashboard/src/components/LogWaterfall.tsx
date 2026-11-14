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
    // Plaintext container stdout line
  }
  return { cleanMessage: raw, level: (fallbackSeverity || "INFO").toUpperCase() };
}

export const LogWaterfall: React.FC<LogWaterfallProps> = ({ logs }) => {
  const [filter, setFilter] = useState<"ALL" | "ANOMALIES" | "CORRELATED">("ALL");

  const filteredLogs = useMemo(() => {
    return logs.filter((log) => {
      if (filter === "ANOMALIES") {
        return log.is_container_anomaly || log.severity === "ERROR";
      }
      if (filter === "CORRELATED") {
        return Boolean(log.trace_id);
      }
      return true;
    });
  }, [logs, filter]);

  return (
    <div className="terminal-card flex flex-col font-mono text-xs">
      <div className="dot-matrix-header flex flex-wrap items-center justify-between gap-2 px-4 py-3">
        <span className="text-[#00ff66] flex items-center gap-2">
          <Terminal className="h-4 w-4" />
          <span>[ 05 // CORRELATED CONTAINER & CLOUDWATCH LOG STREAM ]</span>
        </span>

        <div className="flex items-center gap-1.5 text-[10px]">
          <button
            onClick={() => setFilter("ALL")}
            className={`px-2 py-0.5 border font-bold cursor-pointer ${
              filter === "ALL"
                ? "border-[#00ff66] bg-[#00ff66] text-black"
                : "border-[#262626] bg-[#0a0a0a] text-[#888888] hover:text-white"
            }`}
          >
            ALL ({logs.length})
          </button>
          <button
            onClick={() => setFilter("ANOMALIES")}
            className={`px-2 py-0.5 border font-bold cursor-pointer ${
              filter === "ANOMALIES"
                ? "border-[#ff3333] bg-[#ff3333] text-black"
                : "border-[#262626] bg-[#0a0a0a] text-[#888888] hover:text-white"
            }`}
          >
            OOM / ERRORS
          </button>
          <button
            onClick={() => setFilter("CORRELATED")}
            className={`px-2 py-0.5 border font-bold cursor-pointer ${
              filter === "CORRELATED"
                ? "border-[#00e5ff] bg-[#00e5ff] text-black"
                : "border-[#262626] bg-[#0a0a0a] text-[#888888] hover:text-white"
            }`}
          >
            TRACE LINKED
          </button>
        </div>
      </div>

      <div className="p-3.5 space-y-2.5 max-h-[300px] overflow-y-auto bg-[#030303]">
        {filteredLogs.length === 0 ? (
          <div className="border border-dashed border-[#222222] bg-[#060606] p-6 text-center text-[#666666]">
            NO CONTAINER LOG EVENTS MATCHING FILTER
          </div>
        ) : (
          filteredLogs.map((log) => {
            const { cleanMessage, level } = parseRawLogMessage(log.message, log.severity);
            const isError = level === "ERROR" || log.is_container_anomaly;
            const isWarn = level === "WARN" || level === "WARNING";

            return (
              <div
                key={log.log_id}
                className={`border p-3 text-[11px] transition-colors ${
                  isError
                    ? "border-[#ff3333]/80 bg-[#1a0303] text-[#ff8888]"
                    : isWarn
                    ? "border-[#ffb000]/70 bg-[#191000] text-[#ffd479]"
                    : "border-[#1f1f1f] bg-[#070707] text-[#d4d4d4]"
                }`}
              >
                <div className="flex flex-wrap items-center justify-between gap-2 mb-1.5">
                  <div className="flex items-center gap-2">
                    <span
                      className={`px-1.5 py-0.5 text-[9px] font-extrabold border ${
                        isError
                          ? "border-[#ff3333] bg-[#ff3333] text-black"
                          : isWarn
                          ? "border-[#ffb000] bg-[#ffb000] text-black"
                          : "border-[#00ff66]/50 bg-[#001808] text-[#00ff66]"
                      }`}
                    >
                      {log.is_container_anomaly ? "OOM / ANOMALY" : level}
                    </span>
                    <span className="font-bold text-white">{log.log_stream}</span>
                    <span className="text-[10px] text-[#737373]">
                      {new Date(log.timestamp).toLocaleTimeString()}
                    </span>
                  </div>

                  {log.trace_id && (
                    <span className="inline-flex items-center gap-1 border border-[#00e5ff]/50 bg-[#001820] px-2 py-0.5 text-[10px] font-bold text-[#00e5ff]">
                      <Link2 className="h-3 w-3" />
                      TRACE: {log.trace_id.substring(0, 10)}
                    </span>
                  )}
                </div>

                <div className="flex items-start gap-2 leading-relaxed">
                  {isError && (
                    <AlertTriangle className="h-4 w-4 text-[#ff3333] shrink-0 mt-0.5" />
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
