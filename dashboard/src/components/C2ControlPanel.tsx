import React, { useState } from "react";
import { Check, Edit2, Play, X, ShieldAlert, FileCode, Lock } from "lucide-react";
import { PendingToolCall, CheckpointRecord, AuditLogResponse } from "../types";

interface C2ControlPanelProps {
  sessionId: string | null;
  pendingTools: PendingToolCall[];
  latestCheckpoint: CheckpointRecord | null;
  auditLog: AuditLogResponse | null;
  statusMessage: string | null;
  onApproveTool: (toolCallId: string) => void;
  onEditTool: (toolCallId: string, modifiedArgs: Record<string, unknown>) => void;
  onMockTool: (toolCallId: string, mockOutput: Record<string, unknown>) => void;
  onRejectTool: (toolCallId: string, reason: string) => void;
  onApplyPatch: (patchesJson: string) => void;
}

export const C2ControlPanel: React.FC<C2ControlPanelProps> = ({
  sessionId,
  pendingTools,
  latestCheckpoint,
  auditLog,
  statusMessage,
  onApproveTool,
  onEditTool,
  onMockTool,
  onRejectTool,
  onApplyPatch,
}) => {
  const [selectedToolId, setSelectedToolId] = useState<string | null>(null);
  const [editArgsText, setEditArgsText] = useState<string>("");
  const [mockOutputText, setMockOutputText] = useState<string>('{"mock_result": "Success"}');
  const [rejectReason, setRejectReason] = useState<string>("Security policy violation");
  const [jsonPatchText, setJsonPatchText] = useState<string>(
    '[\n  { "op": "replace", "path": "/plan/0", "value": "Execute safe fallback" }\n]'
  );
  const [mode, setMode] = useState<"approve" | "edit" | "mock" | "reject">("approve");

  const currentTool = pendingTools.find((t) => t.tool_call_id === selectedToolId) || pendingTools[0];

  const handleToolSelect = (tool: PendingToolCall) => {
    setSelectedToolId(tool.tool_call_id);
    setEditArgsText(JSON.stringify(tool.tool_args, null, 2));
  };

  return (
    <div className="terminal-card flex flex-col h-full font-mono text-xs">
      <div className="dot-matrix-header flex items-center justify-between px-4 py-2">
        <span className="text-[#00ff66]">[ 03 // HUMAN-IN-THE-LOOP C2 INTERCEPTOR & STATE CONSOLE ]</span>
        <div className="flex items-center space-x-3">
          {auditLog && (
            <span
              className={`flex items-center space-x-1 text-[10px] px-2 py-0.5 border ${
                auditLog.chain_verified
                  ? "border-[#00ff66] text-[#00ff66] bg-[#001408]"
                  : "border-[#ff3333] text-[#ff3333] bg-[#220000]"
              }`}
            >
              <Lock className="h-3 w-3" />
              <span>
                SHA-256 AUDIT CHAIN: {auditLog.chain_verified ? "VERIFIED" : "TAMPERED"} ({auditLog.entries.length})
              </span>
            </span>
          )}
          <span className="text-[#ffb000]">
            {pendingTools.length} INTERVENTIONS PENDING
          </span>
        </div>
      </div>

      {statusMessage && (
        <div className="mx-3 mt-2 border border-[#00e5ff] bg-[#00151a] px-3 py-1.5 text-[11px] text-[#00e5ff]">
          {statusMessage}
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-3 p-3 flex-1">
        {/* Left Column: Intercepted Tool Calls */}
        <div className="flex flex-col border border-[#222222] bg-[#030303] p-3">
          <div className="flex items-center justify-between mb-2 text-[#888888] font-bold">
            <span className="flex items-center space-x-1.5 text-white">
              <ShieldAlert className="h-4 w-4 text-[#ffb000]" />
              <span>INTERCEPTED MCP / TOOL CALLS</span>
            </span>
          </div>

          {pendingTools.length === 0 ? (
            <div className="flex-1 flex flex-col justify-between text-[#555555]">
              <div className="flex-1 flex items-center justify-center py-6">
                NO INTERCEPTED TOOLS AWAITING OPERATOR DECISION
              </div>
              {auditLog && auditLog.entries.length > 0 && (
                <div className="border-t border-[#1a1a1a] pt-2">
                  <div className="text-[10px] text-[#888888] mb-1">RECENT AUDIT LEDGER ENTRIES:</div>
                  <div className="space-y-1 max-h-24 overflow-y-auto">
                    {auditLog.entries.slice(-3).map((entry) => (
                      <div key={entry.audit_id} className="text-[10px] flex justify-between text-[#aaaaaa]">
                        <span className="text-[#00ff66]">{entry.event_type}</span>
                        <span className="text-[#666666]">HASH: {entry.entry_hash.substring(0, 10)}...</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          ) : (
            <div className="flex flex-col space-y-3 flex-1">
              <div className="flex flex-wrap gap-2">
                {pendingTools.map((t) => (
                  <button
                    key={t.tool_call_id}
                    onClick={() => handleToolSelect(t)}
                    className={`px-2 py-1 text-[11px] border cursor-pointer ${
                      currentTool?.tool_call_id === t.tool_call_id
                        ? "border-[#ffb000] bg-[#1a1200] text-[#ffb000]"
                        : "border-[#333333] text-[#888888] hover:border-[#666666]"
                    }`}
                  >
                    {t.tool_name} ({t.tool_call_id.substring(0, 8)})
                  </button>
                ))}
              </div>

              {currentTool && (
                <div className="flex-1 flex flex-col space-y-2 border border-[#1a1a1a] bg-[#070707] p-2.5">
                  <div className="flex justify-between items-center text-[11px]">
                    <span className="text-white font-bold">{currentTool.tool_name}</span>
                    <span className="text-[#888888]">
                      SHA-256: {currentTool.request_digest_sha256?.substring(0, 10) || "BOUND"}...
                    </span>
                  </div>

                  {/* Mode tabs */}
                  <div className="flex space-x-1 border-b border-[#222222] pb-1">
                    <button
                      onClick={() => setMode("approve")}
                      className={`px-2 py-0.5 text-[10px] cursor-pointer ${
                        mode === "approve" ? "bg-[#00ff66] text-black font-bold" : "text-[#888888]"
                      }`}
                    >
                      APPROVE
                    </button>
                    <button
                      onClick={() => setMode("edit")}
                      className={`px-2 py-0.5 text-[10px] cursor-pointer ${
                        mode === "edit" ? "bg-[#ffb000] text-black font-bold" : "text-[#888888]"
                      }`}
                    >
                      EDIT ARGS
                    </button>
                    <button
                      onClick={() => setMode("mock")}
                      className={`px-2 py-0.5 text-[10px] cursor-pointer ${
                        mode === "mock" ? "bg-[#00e5ff] text-black font-bold" : "text-[#888888]"
                      }`}
                    >
                      INJECT MOCK
                    </button>
                    <button
                      onClick={() => setMode("reject")}
                      className={`px-2 py-0.5 text-[10px] cursor-pointer ${
                        mode === "reject" ? "bg-[#ff3333] text-black font-bold" : "text-[#888888]"
                      }`}
                    >
                      REJECT
                    </button>
                  </div>

                  {/* Form input based on mode */}
                  <div className="flex-1">
                    {mode === "approve" && (
                      <div className="text-[11px] text-[#aaaaaa] p-2 bg-[#030303] border border-[#1a1a1a]">
                        Original Tool Arguments:
                        <pre className="text-white mt-1 overflow-x-auto">
                          {JSON.stringify(currentTool.tool_args, null, 2)}
                        </pre>
                      </div>
                    )}

                    {mode === "edit" && (
                      <textarea
                        value={editArgsText || JSON.stringify(currentTool.tool_args, null, 2)}
                        onChange={(e) => setEditArgsText(e.target.value)}
                        className="w-full h-24 bg-black border border-[#333333] p-2 text-white font-mono text-[11px] focus:outline-none focus:border-[#ffb000]"
                      />
                    )}

                    {mode === "mock" && (
                      <textarea
                        value={mockOutputText}
                        onChange={(e) => setMockOutputText(e.target.value)}
                        className="w-full h-24 bg-black border border-[#333333] p-2 text-white font-mono text-[11px] focus:outline-none focus:border-[#00e5ff]"
                      />
                    )}

                    {mode === "reject" && (
                      <input
                        type="text"
                        value={rejectReason}
                        onChange={(e) => setRejectReason(e.target.value)}
                        className="w-full bg-black border border-[#333333] p-2 text-white font-mono text-[11px] focus:outline-none focus:border-[#ff3333]"
                        placeholder="Rejection explanation..."
                      />
                    )}
                  </div>

                  {/* Submit Action */}
                  <div className="pt-2 flex justify-end">
                    {mode === "approve" && (
                      <button
                        onClick={() => onApproveTool(currentTool.tool_call_id)}
                        className="flex items-center space-x-1 px-3 py-1 bg-[#00ff66] text-black font-bold hover:bg-[#00cc55] cursor-pointer"
                      >
                        <Check className="h-3.5 w-3.5" />
                        <span>AUTHORIZE EXECUTION</span>
                      </button>
                    )}
                    {mode === "edit" && (
                      <button
                        onClick={() => {
                          try {
                            const parsed = JSON.parse(
                              editArgsText || JSON.stringify(currentTool.tool_args)
                            );
                            onEditTool(currentTool.tool_call_id, parsed);
                          } catch {
                            // Handled by parent status
                          }
                        }}
                        className="flex items-center space-x-1 px-3 py-1 bg-[#ffb000] text-black font-bold hover:bg-[#e09b00] cursor-pointer"
                      >
                        <Edit2 className="h-3.5 w-3.5" />
                        <span>SUBMIT EDITED ARGS</span>
                      </button>
                    )}
                    {mode === "mock" && (
                      <button
                        onClick={() => {
                          try {
                            const parsed = JSON.parse(mockOutputText);
                            onMockTool(currentTool.tool_call_id, parsed);
                          } catch {
                            // Handled by parent status
                          }
                        }}
                        className="flex items-center space-x-1 px-3 py-1 bg-[#00e5ff] text-black font-bold hover:bg-[#00c0d8] cursor-pointer"
                      >
                        <Play className="h-3.5 w-3.5" />
                        <span>BYPASS & RETURN MOCK</span>
                      </button>
                    )}
                    {mode === "reject" && (
                      <button
                        onClick={() => onRejectTool(currentTool.tool_call_id, rejectReason)}
                        className="flex items-center space-x-1 px-3 py-1 bg-[#ff3333] text-black font-bold hover:bg-[#e02020] cursor-pointer"
                      >
                        <X className="h-3.5 w-3.5" />
                        <span>BLOCK EXECUTION</span>
                      </button>
                    )}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Right Column: RFC 6902 JSON Patch Memory Editor */}
        <div className="flex flex-col border border-[#222222] bg-[#030303] p-3">
          <div className="flex items-center justify-between mb-2 text-[#888888] font-bold">
            <span className="flex items-center space-x-1.5 text-white">
              <FileCode className="h-4 w-4 text-[#00ff66]" />
              <span>RFC 6902 STATE MUTATION CONSOLE</span>
            </span>
            <span className="text-[10px] text-[#666666]">
              CP: {latestCheckpoint ? latestCheckpoint.checkpoint_id.substring(0, 8) : "NONE"}
            </span>
          </div>

          <div className="flex-1 flex flex-col space-y-2">
            {latestCheckpoint && (
              <div className="border border-[#1a1a1a] bg-[#060606] p-2 text-[10px]">
                <div className="text-[#888888] mb-1">
                  CURRENT MEMORY STATE (STEP #{latestCheckpoint.step_index} • {latestCheckpoint.node_name}):
                </div>
                <pre className="text-[#cccccc] max-h-20 overflow-y-auto">
                  {JSON.stringify(latestCheckpoint.memory_state, null, 2)}
                </pre>
              </div>
            )}

            <div className="text-[11px] text-[#777777]">
              Specify RFC 6902 atomic patch array (session must be PAUSED_C2):
            </div>
            <textarea
              value={jsonPatchText}
              onChange={(e) => setJsonPatchText(e.target.value)}
              className="flex-1 min-h-[110px] w-full bg-black border border-[#333333] p-2 text-[#00ff66] font-mono text-[11px] focus:outline-none focus:border-[#00ff66]"
            />
            <div className="flex justify-between items-center pt-1">
              <span className="text-[10px] text-[#666666]">
                Target: {sessionId ? sessionId.substring(0, 8) + "..." : "No session"}
              </span>
              <button
                disabled={!sessionId}
                onClick={() => onApplyPatch(jsonPatchText)}
                className="px-4 py-1.5 border border-[#00ff66] text-[#00ff66] hover:bg-[#00ff66] hover:text-black font-bold transition-colors cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
              >
                APPLY MEMORY PATCH
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
