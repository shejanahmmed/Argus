import React, { useState } from "react";
import {
  Check,
  Edit2,
  Play,
  X,
  ShieldAlert,
  FileCode,
  Lock,
  Sparkles,
  CheckCircle2,
  Sliders,
} from "lucide-react";
import { PendingToolCall, CheckpointRecord, AuditLogResponse } from "../types";

interface C2ControlPanelProps {
  sessionId: string | null;
  sessionStatus?: string;
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

const PATCH_PRESETS: Array<{ label: string; patch: string }> = [
  {
    label: "PRESET 1: SAFE FALLBACK PLAN",
    patch: JSON.stringify(
      [{ op: "replace", path: "/plan/0", value: "Execute read-only schema audit" }],
      null,
      2
    ),
  },
  {
    label: "PRESET 2: FORCE SANDBOX TARGET",
    patch: JSON.stringify(
      [{ op: "add", path: "/target_env", value: "isolated_sandbox_replica" }],
      null,
      2
    ),
  },
  {
    label: "PRESET 3: CLEAR RETRY LOOP",
    patch: JSON.stringify(
      [{ op: "add", path: "/operator_cleared_loop", value: true }],
      null,
      2
    ),
  },
];

export const C2ControlPanel: React.FC<C2ControlPanelProps> = ({
  sessionId,
  sessionStatus,
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
  const [mockOutputText, setMockOutputText] = useState<string>(
    '{\n  "status": "mocked_by_operator",\n  "rows_affected": 0\n}'
  );
  const [rejectReason, setRejectReason] = useState<string>(
    "Blocked by Zero-Tolerance SecOps Policy: Destructive production DDL prohibited."
  );
  const [jsonPatchText, setJsonPatchText] = useState<string>(PATCH_PRESETS[0].patch);
  const [mode, setMode] = useState<"approve" | "edit" | "mock" | "reject">("approve");

  const currentTool =
    pendingTools.find((t) => t.tool_call_id === selectedToolId) || pendingTools[0];

  const handleToolSelect = (tool: PendingToolCall) => {
    setSelectedToolId(tool.tool_call_id);
    setEditArgsText(JSON.stringify(tool.tool_args, null, 2));
  };

  return (
    <div className="terminal-card flex flex-col font-mono text-xs">
      {/* Header */}
      <div className="dot-matrix-header flex flex-wrap items-center justify-between gap-3 px-4 py-3">
        <div className="flex items-center gap-2">
          <Sliders className="h-4 w-4 text-[#00ff66]" />
          <span className="text-[#00ff66]">
            [ 03 // HUMAN-IN-THE-LOOP C2 INTERCEPTOR & STATE CONSOLE ]
          </span>
        </div>

        <div className="flex flex-wrap items-center gap-2.5">
          {auditLog && (
            <span
              className={`inline-flex items-center gap-1.5 text-[10px] px-2.5 py-1 border font-bold ${
                auditLog.chain_verified
                  ? "border-[#00ff66] text-[#00ff66] bg-[#001808]"
                  : "border-[#ff3333] text-[#ff3333] bg-[#240303]"
              }`}
            >
              <Lock className="h-3 w-3" />
              <span>
                SHA-256 AUDIT CHAIN: {auditLog.chain_verified ? "VERIFIED" : "TAMPERED"} (
                {auditLog.entries.length} BLOCKS)
              </span>
            </span>
          )}
          <span
            className={`px-2.5 py-1 text-[10px] font-bold border ${
              pendingTools.length > 0
                ? "border-[#ffb000] bg-[#1f1300] text-[#ffb000]"
                : "border-[#262626] bg-[#0a0a0a] text-[#737373]"
            }`}
          >
            {pendingTools.length} MCP INTERVENTIONS QUEUED
          </span>
        </div>
      </div>

      {/* Live Status Banner */}
      {statusMessage && (
        <div className="mx-4 mt-3.5 flex items-center gap-2 border border-[#00e5ff] bg-[#001820] px-3.5 py-2.5 text-xs text-[#00e5ff]">
          <CheckCircle2 className="h-4 w-4 shrink-0" />
          <span className="font-semibold">{statusMessage}</span>
        </div>
      )}

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4 p-4">
        {/* Left Column: Intercepted MCP / Tool Calls */}
        <div className="flex flex-col border border-[#222222] bg-[#060606] p-4">
          <div className="flex items-center justify-between pb-3 mb-3 border-b border-[#1a1a1a]">
            <span className="flex items-center gap-2 text-white font-bold">
              <ShieldAlert className="h-4 w-4 text-[#ffb000]" />
              <span>PRE-EXECUTION MCP TOOL GATE</span>
            </span>
            <span className="text-[10px] text-[#737373]">TOCTOU SHA-256 BOUND</span>
          </div>

          {pendingTools.length === 0 ? (
            <div className="flex-1 flex flex-col justify-between">
              <div className="border border-dashed border-[#222222] bg-[#030303] p-6 text-center my-2">
                <div className="text-[#a3a3a3] font-bold mb-1">
                  NO INTERCEPTED TOOL CALLS PENDING
                </div>
                <div className="text-[11px] text-[#666666]">
                  Select a paused session or click [+ SIMULATE MCP GATE] in the top bar to test human-in-the-loop interception.
                </div>
              </div>

              {auditLog && auditLog.entries.length > 0 && (
                <div className="mt-3 pt-3 border-t border-[#1a1a1a]">
                  <div className="text-[10px] font-bold text-[#a3a3a3] mb-2">
                    IMMUTABLE SHA-256 AUDIT LEDGER (LATEST BLOCKS):
                  </div>
                  <div className="space-y-1.5 max-h-36 overflow-y-auto">
                    {auditLog.entries.slice(-4).map((entry) => (
                      <div
                        key={entry.audit_id}
                        className="border border-[#1c1c1c] bg-[#030303] p-2 text-[10px] flex items-center justify-between gap-2"
                      >
                        <div className="flex items-center gap-2">
                          <span className="border border-[#00ff66]/50 bg-[#001808] px-1.5 py-0.5 text-[#00ff66] font-bold">
                            {entry.event_type}
                          </span>
                          <span className="text-[#a3a3a3]">BY {entry.actor_id}</span>
                        </div>
                        <span className="text-[#666666] font-mono">
                          #{entry.entry_hash.substring(0, 12)}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          ) : (
            <div className="flex flex-col space-y-3.5 flex-1">
              {/* Tool selector pills */}
              <div className="flex flex-wrap gap-2">
                {pendingTools.map((t) => (
                  <button
                    key={t.tool_call_id}
                    onClick={() => handleToolSelect(t)}
                    className={`px-3 py-1.5 text-[11px] font-bold border cursor-pointer transition-colors ${
                      currentTool?.tool_call_id === t.tool_call_id
                        ? "border-[#ffb000] bg-[#241600] text-[#ffb000]"
                        : "border-[#2e2e2e] bg-[#0c0c0c] text-[#888888] hover:border-[#555555]"
                    }`}
                  >
                    {t.tool_name} [{t.tool_call_id.substring(0, 8)}]
                  </button>
                ))}
              </div>

              {currentTool && (
                <div className="flex-1 flex flex-col space-y-3 border border-[#242424] bg-[#030303] p-3.5">
                  <div className="flex flex-wrap justify-between items-center gap-2 pb-2.5 border-b border-[#1a1a1a]">
                    <div>
                      <div className="text-white font-bold text-sm">
                        {currentTool.tool_name}
                      </div>
                      <div className="text-[10px] text-[#ff5555] font-semibold mt-0.5">
                        DESTRUCTIVE TOOL SIGNATURE • REQUIRES OPERATOR OVERRIDE
                      </div>
                    </div>
                    <span className="border border-[#2e2e2e] bg-[#0c0c0c] px-2 py-1 text-[10px] text-[#a3a3a3]">
                      DIGEST: {currentTool.request_digest_sha256?.substring(0, 12) || "SHA256"}...
                    </span>
                  </div>

                  {/* Well-spaced Mode Tabs */}
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                    <button
                      onClick={() => setMode("approve")}
                      className={`py-1.5 px-2 text-[10px] font-bold border cursor-pointer transition-colors ${
                        mode === "approve"
                          ? "border-[#00ff66] bg-[#00ff66] text-black"
                          : "border-[#262626] bg-[#0a0a0a] text-[#a3a3a3] hover:text-white"
                      }`}
                    >
                      1. APPROVE
                    </button>
                    <button
                      onClick={() => setMode("edit")}
                      className={`py-1.5 px-2 text-[10px] font-bold border cursor-pointer transition-colors ${
                        mode === "edit"
                          ? "border-[#ffb000] bg-[#ffb000] text-black"
                          : "border-[#262626] bg-[#0a0a0a] text-[#a3a3a3] hover:text-white"
                      }`}
                    >
                      2. EDIT ARGS
                    </button>
                    <button
                      onClick={() => setMode("mock")}
                      className={`py-1.5 px-2 text-[10px] font-bold border cursor-pointer transition-colors ${
                        mode === "mock"
                          ? "border-[#00e5ff] bg-[#00e5ff] text-black"
                          : "border-[#262626] bg-[#0a0a0a] text-[#a3a3a3] hover:text-white"
                      }`}
                    >
                      3. INJECT MOCK
                    </button>
                    <button
                      onClick={() => setMode("reject")}
                      className={`py-1.5 px-2 text-[10px] font-bold border cursor-pointer transition-colors ${
                        mode === "reject"
                          ? "border-[#ff3333] bg-[#ff3333] text-black"
                          : "border-[#262626] bg-[#0a0a0a] text-[#a3a3a3] hover:text-white"
                      }`}
                    >
                      4. REJECT
                    </button>
                  </div>

                  {/* Mode Content Area */}
                  <div className="flex-1">
                    {mode === "approve" && (
                      <div className="border border-[#1c1c1c] bg-[#070707] p-3">
                        <div className="text-[10px] font-bold text-[#737373] mb-1.5">
                          INTERCEPTED JSON-RPC ARGUMENTS:
                        </div>
                        <pre className="text-white text-[11px] overflow-x-auto">
                          {JSON.stringify(currentTool.tool_args, null, 2)}
                        </pre>
                      </div>
                    )}

                    {mode === "edit" && (
                      <div>
                        <div className="text-[10px] text-[#ffb000] mb-1">
                          Modify tool arguments before releasing execution:
                        </div>
                        <textarea
                          value={editArgsText || JSON.stringify(currentTool.tool_args, null, 2)}
                          onChange={(e) => setEditArgsText(e.target.value)}
                          className="w-full h-28 bg-black border border-[#383838] p-2.5 text-white font-mono text-[11px] focus:outline-none focus:border-[#ffb000]"
                        />
                      </div>
                    )}

                    {mode === "mock" && (
                      <div>
                        <div className="text-[10px] text-[#00e5ff] mb-1">
                          Bypass real tool execution and return synthetic JSON payload:
                        </div>
                        <textarea
                          value={mockOutputText}
                          onChange={(e) => setMockOutputText(e.target.value)}
                          className="w-full h-28 bg-black border border-[#383838] p-2.5 text-[#00e5ff] font-mono text-[11px] focus:outline-none focus:border-[#00e5ff]"
                        />
                      </div>
                    )}

                    {mode === "reject" && (
                      <div>
                        <div className="text-[10px] text-[#ff5555] mb-1">
                          Rejection reason returned to agent runtime:
                        </div>
                        <input
                          type="text"
                          value={rejectReason}
                          onChange={(e) => setRejectReason(e.target.value)}
                          className="w-full bg-black border border-[#383838] p-2.5 text-white font-mono text-[11px] focus:outline-none focus:border-[#ff3333]"
                        />
                      </div>
                    )}
                  </div>

                  {/* Submit Action Button */}
                  <div className="pt-2 flex justify-end">
                    {mode === "approve" && (
                      <button
                        onClick={() => onApproveTool(currentTool.tool_call_id)}
                        className="flex items-center gap-2 px-4 py-2 bg-[#00ff66] text-black font-bold hover:bg-[#00cc55] transition-colors cursor-pointer"
                      >
                        <Check className="h-4 w-4" />
                        <span>AUTHORIZE TOOL EXECUTION</span>
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
                            // Handled by parent
                          }
                        }}
                        className="flex items-center gap-2 px-4 py-2 bg-[#ffb000] text-black font-bold hover:bg-[#e09b00] transition-colors cursor-pointer"
                      >
                        <Edit2 className="h-4 w-4" />
                        <span>COMMIT EDITED ARGUMENTS</span>
                      </button>
                    )}
                    {mode === "mock" && (
                      <button
                        onClick={() => {
                          try {
                            const parsed = JSON.parse(mockOutputText);
                            onMockTool(currentTool.tool_call_id, parsed);
                          } catch {
                            // Handled by parent
                          }
                        }}
                        className="flex items-center gap-2 px-4 py-2 bg-[#00e5ff] text-black font-bold hover:bg-[#00c0d8] transition-colors cursor-pointer"
                      >
                        <Play className="h-4 w-4" />
                        <span>BYPASS & INJECT MOCK</span>
                      </button>
                    )}
                    {mode === "reject" && (
                      <button
                        onClick={() => onRejectTool(currentTool.tool_call_id, rejectReason)}
                        className="flex items-center gap-2 px-4 py-2 bg-[#ff3333] text-black font-bold hover:bg-[#e02020] transition-colors cursor-pointer"
                      >
                        <X className="h-4 w-4" />
                        <span>ABORT & REJECT TOOL CALL</span>
                      </button>
                    )}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Right Column: RFC 6902 State Mutation Console */}
        <div className="flex flex-col border border-[#222222] bg-[#060606] p-4">
          <div className="flex items-center justify-between pb-3 mb-3 border-b border-[#1a1a1a]">
            <span className="flex items-center gap-2 text-white font-bold">
              <FileCode className="h-4 w-4 text-[#00ff66]" />
              <span>RFC 6902 MEMORY STATE PATCH CONSOLE</span>
            </span>
            <span className="border border-[#2e2e2e] bg-[#0c0c0c] px-2 py-0.5 text-[10px] text-[#00ff66]">
              HEAD CP: {latestCheckpoint ? latestCheckpoint.checkpoint_id.substring(0, 8) : "NONE"}
            </span>
          </div>

          <div className="flex-1 flex flex-col space-y-3">
            {latestCheckpoint ? (
              <div className="border border-[#1f1f1f] bg-[#030303] p-3">
                <div className="flex items-center justify-between text-[10px] text-[#888888] mb-1.5">
                  <span className="font-bold text-[#a3a3a3]">
                    CHECKPOINT SNAPSHOT (STEP #{latestCheckpoint.step_index} •{" "}
                    {latestCheckpoint.node_name})
                  </span>
                  <span className="text-[#00ff66]">OPTIMISTIC LOCK ACTIVE</span>
                </div>
                <pre className="text-[#d4d4d4] text-[11px] max-h-24 overflow-y-auto">
                  {JSON.stringify(latestCheckpoint.memory_state, null, 2)}
                </pre>
              </div>
            ) : (
              <div className="border border-dashed border-[#222222] bg-[#030303] p-3 text-[11px] text-[#666666]">
                No checkpoint snapshot recorded on this session yet. Select the CrewAI Paused C2 session to inspect and mutate live memory state.
              </div>
            )}

            {/* One-Click Patch Presets */}
            <div>
              <div className="text-[10px] font-bold text-[#737373] mb-1.5 flex items-center gap-1">
                <Sparkles className="h-3 w-3 text-[#00e5ff]" />
                ONE-CLICK RFC 6902 PATCH TEMPLATES:
              </div>
              <div className="flex flex-wrap gap-1.5">
                {PATCH_PRESETS.map((preset, i) => (
                  <button
                    key={i}
                    onClick={() => setJsonPatchText(preset.patch)}
                    className="px-2.5 py-1 text-[10px] border border-[#2a2a2a] bg-[#0c0c0c] text-[#a3a3a3] hover:border-[#00e5ff] hover:text-[#00e5ff] transition-colors cursor-pointer"
                  >
                    {preset.label}
                  </button>
                ))}
              </div>
            </div>

            <textarea
              value={jsonPatchText}
              onChange={(e) => setJsonPatchText(e.target.value)}
              className="flex-1 min-h-[115px] w-full bg-black border border-[#333333] p-3 text-[#00ff66] font-mono text-[11px] focus:outline-none focus:border-[#00ff66]"
            />

            <div className="flex flex-wrap justify-between items-center gap-2 pt-1">
              <span className="text-[10px] text-[#737373]">
                STATUS:{" "}
                <strong className="text-white">{sessionStatus || "NONE"}</strong>{" "}
                {sessionStatus !== "PAUSED_C2" && (
                  <span className="text-[#ffb000]">(Click PAUSE C2 / UNLOCK C2 to edit)</span>
                )}
              </span>

              <button
                disabled={!sessionId}
                onClick={() => onApplyPatch(jsonPatchText)}
                className="px-4 py-2 border border-[#00ff66] bg-[#001a09] text-[#00ff66] hover:bg-[#00ff66] hover:text-black font-bold tracking-wider transition-all cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
              >
                COMMIT RFC 6902 MEMORY PATCH
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
