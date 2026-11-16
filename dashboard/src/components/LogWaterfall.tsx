import React, { useState, useMemo, useRef, useEffect } from "react";
import {
  Terminal,
  AlertTriangle,
  Link2,
  Search,
  X,
  Copy,
  Check,
  ChevronRight,
  ChevronDown,
  ArrowDown,
} from "lucide-react";
import { ContainerLog } from "../types";

interface LogWaterfallProps {
  logs: ContainerLog[];
}

interface ParsedLogContent {
  cleanMessage: string;
  level: string;
  rawJson: Record<string, unknown> | null;
}

function parseRawLogMessage(raw: string, fallbackSeverity: string): ParsedLogContent {
  try {
    const parsed = JSON.parse(raw);
    if (typeof parsed === "object" && parsed !== null) {
      return {
        cleanMessage: String(parsed.msg || parsed.message || raw),
        level: String(parsed.level || fallbackSeverity || "INFO").toUpperCase(),
        rawJson: parsed as Record<string, unknown>,
      };
    }
  } catch {
    // Plaintext line
  }
  return {
    cleanMessage: raw,
    level: (fallbackSeverity || "INFO").toUpperCase(),
    rawJson: null,
  };
}

export const LogWaterfall: React.FC<LogWaterfallProps> = ({ logs }) => {
  const [filter, setFilter] = useState<"ALL" | "ANOMALIES" | "CORRELATED">("ALL");
  const [searchQuery, setSearchQuery] = useState<string>("");
  const [expandedLogId, setExpandedLogId] = useState<string | null>(null);
  const [autoScroll, setAutoScroll] = useState<boolean>(true);
  const [copiedLogId, setCopiedLogId] = useState<string | null>(null);

  const scrollRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom on new logs when live tail is enabled
  useEffect(() => {
    if (autoScroll && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [logs, autoScroll]);

  const handleCopyLog = (id: string, text: string) => {
    try {
      navigator.clipboard.writeText(text);
      setCopiedLogId(id);
      setTimeout(() => setCopiedLogId(null), 2000);
    } catch {
      // Fallback
    }
  };

  const anomaliesCount = useMemo(
    () => logs.filter((l) => l.is_container_anomaly || l.severity === "ERROR").length,
    [logs]
  );

  const correlatedCount = useMemo(
    () => logs.filter((l) => Boolean(l.trace_id || l.session_id)).length,
    [logs]
  );

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
        const matchesTrace = log.trace_id ? log.trace_id.toLowerCase().includes(q) : false;
        const matchesSess = log.session_id ? log.session_id.toLowerCase().includes(q) : false;
        if (!matchesMsg && !matchesStream && !matchesAnomaly && !matchesTrace && !matchesSess) {
          return false;
        }
      }
      return true;
    });
  }, [logs, filter, searchQuery]);

  return (
    <div className="rounded-xl border border-[#222228] bg-[#111114] flex flex-col shadow-sm">
      {/* Panel Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between px-4 py-3 border-b border-[#222228] bg-[#0d0d10] rounded-t-xl gap-3">
        <div className="flex items-center gap-2.5">
          <div className="flex h-6 w-6 items-center justify-center rounded-md bg-[#18181b] border border-[#27272a] text-zinc-300">
            <Terminal className="h-3.5 w-3.5 text-zinc-400" />
          </div>
          <div className="flex items-center gap-2">
            <h2 className="text-xs font-semibold text-zinc-100 uppercase tracking-wider">
              Container Log Stream
            </h2>
            <span className="rounded-full bg-[#18181b] px-2 py-0.5 text-[10px] font-mono font-medium text-zinc-400 border border-[#27272a]">
              {logs.length} entries
            </span>
          </div>
        </div>

        {/* Live Tail Toggle */}
        <div className="flex items-center gap-2">
          <button
            onClick={() => setAutoScroll((prev) => !prev)}
            className={`flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[11px] font-mono border transition-colors cursor-pointer ${
              autoScroll
                ? "bg-[#18181b] border-emerald-500/40 text-emerald-400"
                : "bg-[#141418] border-[#222228] text-zinc-400 hover:text-zinc-200"
            }`}
            title="Auto-scroll viewport to latest incoming logs"
          >
            <ArrowDown className={`h-3 w-3 ${autoScroll ? "animate-bounce" : ""}`} />
            <span>Tail: {autoScroll ? "ON" : "OFF"}</span>
          </button>
        </div>
      </div>

      {/* Filter & Search Toolbar */}
      <div className="px-4 py-2 border-b border-[#1f1f26] bg-[#0f0f13] flex flex-col sm:flex-row gap-2.5 items-stretch sm:items-center justify-between">
        {/* Search Input */}
        <div className="relative flex-1">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-zinc-500" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search logs, streams, traces, or anomalies..."
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
        <div className="flex items-center gap-1 shrink-0">
          <button
            onClick={() => setFilter("ALL")}
            className={`px-2 py-0.5 rounded text-[11px] font-medium transition-colors cursor-pointer ${
              filter === "ALL"
                ? "bg-[#222228] text-white border border-zinc-600/80 shadow-2xs"
                : "text-zinc-500 hover:text-zinc-300 hover:bg-[#141418]"
            }`}
          >
            All ({logs.length})
          </button>
          <button
            onClick={() => setFilter("ANOMALIES")}
            className={`px-2 py-0.5 rounded text-[11px] font-medium transition-colors cursor-pointer ${
              filter === "ANOMALIES"
                ? "bg-[#222228] text-white border border-zinc-600/80 shadow-2xs"
                : "text-zinc-500 hover:text-zinc-300 hover:bg-[#141418]"
            }`}
          >
            Errors & OOM ({anomaliesCount})
          </button>
          <button
            onClick={() => setFilter("CORRELATED")}
            className={`px-2 py-0.5 rounded text-[11px] font-medium transition-colors cursor-pointer ${
              filter === "CORRELATED"
                ? "bg-[#222228] text-white border border-zinc-600/80 shadow-2xs"
                : "text-zinc-500 hover:text-zinc-300 hover:bg-[#141418]"
            }`}
          >
            Trace Linked ({correlatedCount})
          </button>
        </div>
      </div>

      {/* Terminal Viewport */}
      <div
        ref={scrollRef}
        className="p-3 space-y-1.5 max-h-[360px] overflow-y-auto font-mono text-xs bg-[#09090b]"
      >
        {filteredLogs.length === 0 ? (
          <div className="rounded-lg border border-dashed border-[#222228] bg-[#111114]/50 p-6 text-center text-zinc-500 font-sans text-xs">
            No container log entries matching active filter &ldquo;{searchQuery || filter}&rdquo;.
          </div>
        ) : (
          filteredLogs.map((log) => {
            const { cleanMessage, level, rawJson } = parseRawLogMessage(
              log.message,
              log.severity
            );
            const isError = level === "ERROR" || log.is_container_anomaly;
            const isWarn = level === "WARN" || level === "WARNING";
            const isExpanded = expandedLogId === log.log_id;

            const anomalyLabel = log.anomaly_type
              ? log.anomaly_type.replace(/_/g, " ")
              : log.is_container_anomaly
              ? "OOM Crash"
              : level;

            return (
              <div
                key={log.log_id}
                className={`rounded-lg border transition-all ${
                  isError
                    ? "border-rose-500/30 bg-[#161014] text-rose-300"
                    : isWarn
                    ? "border-amber-500/30 bg-[#161410] text-amber-300"
                    : "border-[#1f1f26] bg-[#111114] text-zinc-300 hover:border-[#27272a]"
                }`}
              >
                {/* Main Row */}
                <div
                  onClick={() => setExpandedLogId(isExpanded ? null : log.log_id)}
                  className="p-2.5 flex flex-wrap items-center justify-between gap-2 cursor-pointer select-none"
                >
                  <div className="flex items-center gap-2 flex-wrap min-w-0">
                    <span className="text-zinc-500 text-[10px] shrink-0">
                      {isExpanded ? (
                        <ChevronDown className="h-3 w-3" />
                      ) : (
                        <ChevronRight className="h-3 w-3" />
                      )}
                    </span>

                    {/* Timestamp */}
                    <span className="text-[10px] text-zinc-500 shrink-0">
                      {new Date(log.timestamp).toLocaleTimeString()}
                    </span>

                    {/* Level Badge */}
                    <span
                      className={`rounded px-1.5 py-0.5 text-[9px] font-mono font-medium border uppercase shrink-0 ${
                        isError
                          ? "border-rose-500/30 bg-rose-500/10 text-rose-400"
                          : isWarn
                          ? "border-amber-500/30 bg-amber-500/10 text-amber-400"
                          : "border-[#27272a] bg-[#18181b] text-zinc-300"
                      }`}
                    >
                      {anomalyLabel}
                    </span>

                    {/* Stream Tag */}
                    <span className="text-zinc-400 font-sans font-medium text-xs truncate max-w-[140px]">
                      {log.log_stream}
                    </span>

                    {/* Correlated IDs */}
                    {log.session_id && (
                      <span className="rounded bg-[#18181b] border border-[#27272a] px-1.5 py-0.5 text-[10px] font-mono text-purple-400 shrink-0">
                        sess: {log.session_id.substring(0, 8)}
                      </span>
                    )}

                    {log.trace_id && (
                      <span className="inline-flex items-center gap-1 rounded bg-[#18181b] border border-[#27272a] px-1.5 py-0.5 text-[10px] font-mono text-sky-400 shrink-0">
                        <Link2 className="h-2.5 w-2.5" />
                        trace: {log.trace_id.substring(0, 8)}
                      </span>
                    )}
                  </div>

                  {/* Copy Action */}
                  <div
                    className="flex items-center gap-2"
                    onClick={(e) => e.stopPropagation()}
                  >
                    <button
                      onClick={() => handleCopyLog(log.log_id, log.message)}
                      className="text-zinc-500 hover:text-zinc-300 p-1 rounded cursor-pointer transition-colors"
                      title="Copy raw log line"
                    >
                      {copiedLogId === log.log_id ? (
                        <Check className="h-3 w-3 text-emerald-400" />
                      ) : (
                        <Copy className="h-3 w-3" />
                      )}
                    </button>
                  </div>
                </div>

                {/* Message Body */}
                <div className="px-2.5 pb-2 text-[11px] leading-relaxed break-words font-mono text-zinc-200">
                  {isError && (
                    <AlertTriangle className="h-3 w-3 text-rose-400 inline-block mr-1.5 -mt-0.5" />
                  )}
                  {cleanMessage}
                </div>

                {/* Expanded Raw JSON Drawer */}
                {isExpanded && (
                  <div className="px-2.5 pb-2.5 pt-1.5 border-t border-[#1f1f26] bg-[#09090b] rounded-b-lg space-y-2">
                    <div className="flex items-center justify-between text-[10px] text-zinc-500">
                      <span>Raw Log ID: {log.log_id}</span>
                      <span>Ingest Timestamp: {new Date(log.timestamp).toISOString()}</span>
                    </div>

                    <pre className="p-2 rounded bg-[#111114] border border-[#1f1f26] text-[10px] text-zinc-300 overflow-x-auto max-h-36">
                      {rawJson
                        ? JSON.stringify(rawJson, null, 2)
                        : JSON.stringify(log, null, 2)}
                    </pre>
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>
    </div>
  );
};
