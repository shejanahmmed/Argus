import React from "react";
import { Terminal, AlertTriangle } from "lucide-react";
import { ContainerLog } from "../types";

interface LogWaterfallProps {
  logs: ContainerLog[];
}

export const LogWaterfall: React.FC<LogWaterfallProps> = ({ logs }) => {
  return (
    <div className="terminal-card flex flex-col h-full font-mono text-xs">
      <div className="dot-matrix-header flex items-center justify-between px-4 py-2">
        <span className="text-[#00ff66] flex items-center space-x-1.5">
          <Terminal className="h-3.5 w-3.5" />
          <span>[ 05 // CORRELATED CONTAINER LOG STREAM ]</span>
        </span>
        <span className="text-[#666666]">{logs.length} LOG EVENTS</span>
      </div>

      <div className="flex-1 overflow-y-auto max-h-[220px] p-2 space-y-1 bg-[#020202]">
        {logs.length === 0 ? (
          <div className="h-full flex items-center justify-center text-[#555555] py-8">
            WAITING FOR CONTAINER / CLOUDWATCH LOG INGESTION...
          </div>
        ) : (
          logs.map((log) => {
            const isError = log.severity === "ERROR" || log.is_container_anomaly;
            return (
              <div
                key={log.log_id}
                className={`flex items-start space-x-2 p-1.5 border text-[11px] ${
                  isError
                    ? "border-[#ff3333] bg-[#1a0000] text-[#ff6666]"
                    : "border-[#151515] bg-[#050505] text-[#cccccc]"
                }`}
              >
                {isError && <AlertTriangle className="h-3.5 w-3.5 text-[#ff3333] shrink-0 mt-0.5" />}
                <span className="text-[#666666] shrink-0">
                  {new Date(log.timestamp).toLocaleTimeString()}
                </span>
                <span className="text-[#888888] shrink-0">[{log.log_stream}]</span>
                <span className="flex-1 break-all">{log.message}</span>
                {log.trace_id && (
                  <span className="text-[#00e5ff] shrink-0 text-[10px]">
                    TRACE: {log.trace_id.substring(0, 8)}
                  </span>
                )}
              </div>
            );
          })
        )}
      </div>
    </div>
  );
};
