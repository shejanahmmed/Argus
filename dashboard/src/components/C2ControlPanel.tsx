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
  SlidersHorizontal,
  CheckCircle2,
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
    label: "Safe Fallback Plan",
    patch: JSON.stringify(
      [{ op: "replace", path: "/plan/0", value: "Execute read-only schema audit" }],
      null,
      2
    ),
  },
  {
    label: "Force Sandbox Replica",
    patch: JSON.stringify(
      [{ op: "add", path: "/target_env", value: "isolated_sandbox_replica" }],
      null,
      2
    ),
  },
  {
    label: "Clear Retry Loop Flag",
    patch: JSON.stringify(
      [{ op: "add", path: "/operator_cleared_loop", value: true }],
      null,
      2
    ),
  },
  {
    label: "Budget Throttle Mode",
    patch: JSON.stringify(
      [
        { op: "add", path: "/model_tier", value: "lightweight" },
        { op: "add", path: "/max_tokens_per_step", value: 256 },
        { op: "add", path: "/allow_expensive_tools", value: false },
      ],
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
    <div className="rounded-xl border border-zinc-800 bg-[#121215] flex flex-col shadow-sm">
      {/* Header */}
      <div className="flex items-center justify-between px-5 py-4 border-b border-zinc-800">
        <div className="flex items-center gap-2.5">
          <SlidersHorizontal className="h-4 w-4 text-zinc-400" />
          <h2 className="text-sm font-semibold text-zinc-100">Human-in-the-Loop C2 Governance</h2>
        </div>

        <div className="flex items-center gap-3">
          {auditLog && (
            <span
              className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium border ${
                auditLog.chain_verified
                  ? "border-emerald-500/20 bg-emerald-500/10 text-emerald-400"
                  : "border-rose-500/20 bg-rose-500/10 text-rose-400"
              }`}
            >
              <Lock className="h-3 w-3" />
              <span>SHA-256 Audit Chain: {auditLog.chain_verified ? "Verified" : "Tampered"}</span>
            </span>
          )}
          <span
            className={`rounded-full px-2.5 py-0.5 text-xs font-medium border ${
              pendingTools.length > 0
                ? "border-amber-500/20 bg-amber-500/10 text-amber-400"
                : "border-zinc-800 bg-zinc-900 text-zinc-400"
            }`}
          >
            {pendingTools.length} Pending
          </span>
        </div>
      </div>

      {/* Status Notice */}
      {statusMessage && (
        <div className="mx-5 mt-4 flex items-center gap-2 rounded-lg border border-sky-500/20 bg-sky-500/10 px-3.5 py-2.5 text-xs text-sky-300">
          <CheckCircle2 className="h-4 w-4 shrink-0 text-sky-400" />
          <span>{statusMessage}</span>
        </div>
      )}

      {/* Grid of Two Columns */}
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4 p-5">
        {/* Left Column: Intercepted Tool Queue */}
        <div className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-4 flex flex-col">
          <div className="flex items-center justify-between pb-3 mb-3 border-b border-zinc-800">
            <span className="flex items-center gap-2 text-sm font-medium text-white">
              <ShieldAlert className="h-4 w-4 text-amber-400" />
              <span>Intercepted MCP Tool Calls</span>
            </span>
            <span className="text-xs text-zinc-500">Cryptographically Bound</span>
          </div>

          {pendingTools.length === 0 ? (
            <div className="flex-1 flex flex-col justify-between py-6">
              <div className="rounded-lg border border-dashed border-zinc-800 bg-zinc-950/40 p-6 text-center text-xs text-zinc-500">
                No tool calls currently awaiting human operator authorization.
              </div>

              {auditLog && auditLog.entries.length > 0 && (
                <div className="mt-4 pt-3 border-t border-zinc-800">
                  <div className="text-xs font-medium text-zinc-400 mb-2">Recent Audit Trail</div>
                  <div className="space-y-1.5 max-h-36 overflow-y-auto">
                    {auditLog.entries.slice(-3).map((entry) => (
                      <div
                        key={entry.audit_id}
                        className="rounded border border-zinc-800 bg-zinc-950 px-2.5 py-1.5 text-xs flex items-center justify-between text-zinc-400 font-mono"
                      >
                        <span className="text-emerald-400 font-medium">{entry.event_type}</span>
                        <span className="text-zinc-500 text-[11px]">#{entry.entry_hash.substring(0, 10)}...</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          ) : (
            <div className="space-y-3 flex-1 flex flex-col">
              {/* Tool selector pills */}
              <div className="flex flex-wrap gap-2">
                {pendingTools.map((t) => (
                  <button
                    key={t.tool_call_id}
                    onClick={() => handleToolSelect(t)}
                    className={`px-2.5 py-1 text-xs rounded font-medium border cursor-pointer transition-colors ${
                      currentTool?.tool_call_id === t.tool_call_id
                        ? "border-amber-500/40 bg-amber-500/10 text-amber-300"
                        : "border-zinc-800 bg-zinc-900 text-zinc-400 hover:text-white"
                    }`}
                  >
                    {t.tool_name}
                  </button>
                ))}
              </div>

              {currentTool && (
                <div className="rounded-lg border border-zinc-800 bg-zinc-950 p-4 space-y-3 flex-1 flex flex-col">
                  <div className="flex items-center justify-between pb-2 border-b border-zinc-800/80">
                    <div>
                      <div className="text-sm font-semibold text-white">{currentTool.tool_name}</div>
                      {currentTool.is_destructive && (
                        <div className="text-xs text-rose-400 font-medium mt-0.5">Destructive Operation</div>
                      )}
                      {currentTool.security_risk && (
                        <div className="text-xs text-amber-400 font-medium mt-0.5">
                          Security Threat: {currentTool.security_risk}
                        </div>
                      )}
                    </div>
                    <span
                      className="text-[11px] font-mono text-zinc-500 hover:text-zinc-300 transition-colors"
                      title={currentTool.request_digest_sha256}
                    >
                      SHA: {currentTool.request_digest_sha256 ? currentTool.request_digest_sha256.substring(0, 10) : "N/A"}...
                    </span>
                  </div>

                  {/* Mode tabs */}
                  <div className="flex rounded-lg bg-zinc-900 p-1 border border-zinc-800">
                    <button
                      onClick={() => setMode("approve")}
                      className={`flex-1 py-1 text-xs font-medium rounded cursor-pointer ${
                        mode === "approve" ? "bg-zinc-800 text-white" : "text-zinc-400"
                      }`}
                    >
                      Approve
                    </button>
                    <button
                      onClick={() => setMode("edit")}
                      className={`flex-1 py-1 text-xs font-medium rounded cursor-pointer ${
                        mode === "edit" ? "bg-zinc-800 text-white" : "text-zinc-400"
                      }`}
                    >
                      Edit Args
                    </button>
                    <button
                      onClick={() => setMode("mock")}
                      className={`flex-1 py-1 text-xs font-medium rounded cursor-pointer ${
                        mode === "mock" ? "bg-zinc-800 text-white" : "text-zinc-400"
                      }`}
                    >
                      Inject Mock
                    </button>
                    <button
                      onClick={() => setMode("reject")}
                      className={`flex-1 py-1 text-xs font-medium rounded cursor-pointer ${
                        mode === "reject" ? "bg-zinc-800 text-white" : "text-zinc-400"
                      }`}
                    >
                      Reject
                    </button>
                  </div>

                  {/* Action Content */}
                  <div className="flex-1">
                    {mode === "approve" && (
                      <div className="rounded border border-zinc-800 bg-zinc-900/50 p-3">
                        <div className="text-xs text-zinc-400 mb-1 font-medium">Arguments to Execute:</div>
                        <pre className="text-xs text-zinc-200 font-mono overflow-x-auto">
                          {JSON.stringify(currentTool.tool_args, null, 2)}
                        </pre>
                      </div>
                    )}

                    {mode === "edit" && (
                      <textarea
                        value={editArgsText || JSON.stringify(currentTool.tool_args, null, 2)}
                        onChange={(e) => setEditArgsText(e.target.value)}
                        className="w-full h-24 rounded border border-zinc-800 bg-zinc-900 p-2.5 text-xs text-white font-mono focus:outline-none focus:border-zinc-600"
                      />
                    )}

                    {mode === "mock" && (
                      <textarea
                        value={mockOutputText}
                        onChange={(e) => setMockOutputText(e.target.value)}
                        className="w-full h-24 rounded border border-zinc-800 bg-zinc-900 p-2.5 text-xs text-white font-mono focus:outline-none focus:border-zinc-600"
                      />
                    )}

                    {mode === "reject" && (
                      <input
                        type="text"
                        value={rejectReason}
                        onChange={(e) => setRejectReason(e.target.value)}
                        className="w-full rounded border border-zinc-800 bg-zinc-900 p-2.5 text-xs text-white focus:outline-none focus:border-zinc-600"
                      />
                    )}
                  </div>

                  {/* Submit Button */}
                  <div className="pt-2 flex justify-end">
                    {mode === "approve" && (
                      <button
                        onClick={() => onApproveTool(currentTool.tool_call_id)}
                        className="flex items-center gap-1.5 rounded-md bg-emerald-500 hover:bg-emerald-400 text-zinc-950 font-medium px-3.5 py-1.5 text-xs transition-colors cursor-pointer"
                      >
                        <Check className="h-3.5 w-3.5" />
                        <span>Authorize Tool Call</span>
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
                        className="flex items-center gap-1.5 rounded-md bg-amber-500 hover:bg-amber-400 text-zinc-950 font-medium px-3.5 py-1.5 text-xs transition-colors cursor-pointer"
                      >
                        <Edit2 className="h-3.5 w-3.5" />
                        <span>Save & Authorize</span>
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
                        className="flex items-center gap-1.5 rounded-md bg-sky-500 hover:bg-sky-400 text-zinc-950 font-medium px-3.5 py-1.5 text-xs transition-colors cursor-pointer"
                      >
                        <Play className="h-3.5 w-3.5" />
                        <span>Inject Mock Response</span>
                      </button>
                    )}
                    {mode === "reject" && (
                      <button
                        onClick={() => onRejectTool(currentTool.tool_call_id, rejectReason)}
                        className="flex items-center gap-1.5 rounded-md bg-rose-500 hover:bg-rose-400 text-zinc-950 font-medium px-3.5 py-1.5 text-xs transition-colors cursor-pointer"
                      >
                        <X className="h-3.5 w-3.5" />
                        <span>Reject Tool Call</span>
                      </button>
                    )}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Right Column: RFC 6902 State Mutation */}
        <div className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-4 flex flex-col">
          <div className="flex items-center justify-between pb-3 mb-3 border-b border-zinc-800">
            <span className="flex items-center gap-2 text-sm font-medium text-white">
              <FileCode className="h-4 w-4 text-emerald-400" />
              <span>RFC 6902 State Mutation</span>
            </span>
            <span className="text-xs text-zinc-500 font-mono">
              CP: {latestCheckpoint ? latestCheckpoint.checkpoint_id.substring(0, 8) : "None"}
            </span>
          </div>

          <div className="space-y-3 flex-1 flex flex-col">
            {latestCheckpoint ? (
              <div className="rounded border border-zinc-800 bg-zinc-950 p-3">
                <div className="flex justify-between text-xs text-zinc-400 mb-1">
                  <span>State at Step #{latestCheckpoint.step_index} ({latestCheckpoint.node_name})</span>
                  <span className="text-emerald-400 font-medium">Optimistic Lock Active</span>
                </div>
                <pre className="text-xs text-zinc-300 font-mono max-h-24 overflow-y-auto">
                  {JSON.stringify(latestCheckpoint.memory_state, null, 2)}
                </pre>
              </div>
            ) : (
              <div className="rounded border border-dashed border-zinc-800 bg-zinc-950/40 p-3 text-xs text-zinc-500">
                No checkpoint snapshot on current session.
              </div>
            )}

            {/* Presets */}
            <div>
              <div className="text-xs text-zinc-400 mb-1.5 font-medium flex items-center gap-1">
                <Sparkles className="h-3 w-3 text-zinc-400" />
                <span>Patch Presets:</span>
              </div>
              <div className="flex flex-wrap gap-1.5">
                {PATCH_PRESETS.map((preset, i) => (
                  <button
                    key={i}
                    onClick={() => setJsonPatchText(preset.patch)}
                    className="rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-300 px-2 py-1 text-xs border border-zinc-700/60 transition-colors cursor-pointer"
                  >
                    {preset.label}
                  </button>
                ))}
              </div>
            </div>

            <textarea
              value={jsonPatchText}
              onChange={(e) => setJsonPatchText(e.target.value)}
              className="flex-1 min-h-[110px] w-full rounded border border-zinc-800 bg-zinc-950 p-3 text-xs text-zinc-200 font-mono focus:outline-none focus:border-zinc-600"
            />

            <div className="flex items-center justify-between pt-1">
              <span className="text-xs text-zinc-500">
                Status: <strong className="text-zinc-200 font-medium">{sessionStatus || "None"}</strong>
              </span>

              <button
                disabled={!sessionId}
                onClick={() => onApplyPatch(jsonPatchText)}
                className="rounded-md bg-zinc-100 hover:bg-white text-zinc-950 px-3.5 py-1.5 text-xs font-semibold shadow-sm transition-all cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
              >
                Apply State Patch
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
