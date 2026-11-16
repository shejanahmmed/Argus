import React, { useState } from "react";
import {
  Check,
  Edit2,
  Play,
  X,
  ShieldAlert,
  FileCode,
  Lock,
  SlidersHorizontal,
  CheckCircle2,
  Radio,
  Timer,
  Activity,
  Download,
  AlertTriangle,
  ChevronDown,
  ChevronUp,
  Bookmark,
  Copy,
} from "lucide-react";
import { PendingToolCall, CheckpointRecord, AuditLogResponse, WorkerLease } from "../types";

interface C2ControlPanelProps {
  sessionId: string | null;
  sessionStatus?: string;
  pendingTools: PendingToolCall[];
  latestCheckpoint: CheckpointRecord | null;
  auditLog: AuditLogResponse | null;
  statusMessage: string | null;
  activeLease?: WorkerLease | null;
  onApproveTool: (toolCallId: string) => void;
  onEditTool: (toolCallId: string, modifiedArgs: Record<string, unknown>) => void;
  onMockTool: (toolCallId: string, mockOutput: Record<string, unknown>) => void;
  onRejectTool: (toolCallId: string, reason: string) => void;
  onApplyPatch: (patchesJson: string) => void;
  onReapLeases?: () => void;
  authFetch?: (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;
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
  activeLease,
  onApproveTool,
  onEditTool,
  onMockTool,
  onRejectTool,
  onApplyPatch,
  onReapLeases,
  authFetch,
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
  const [showAuditChain, setShowAuditChain] = useState<boolean>(false);
  const [copiedHash, setCopiedHash] = useState<string | null>(null);

  const handleCopyHash = (hash: string) => {
    try {
      navigator.clipboard.writeText(hash);
      setCopiedHash(hash);
      setTimeout(() => setCopiedHash(null), 2000);
    } catch {
      // Fallback
    }
  };

  const handleExportAudit = async (format: "json" | "csv" = "json") => {
    if (!sessionId) return;
    try {
      const fetchFn = authFetch || fetch;
      const res = await fetchFn(`/api/v1/c2/${sessionId}/audit-log/export?format=${format}`);
      if (res.ok) {
        const blob = await res.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `audit_${sessionId}.${format}`;
        a.click();
        window.URL.revokeObjectURL(url);
      }
    } catch {
      // Fallback
    }
  };

  const currentTool =
    pendingTools.find((t) => t.tool_call_id === selectedToolId) || pendingTools[0];

  const handleToolSelect = (tool: PendingToolCall) => {
    setSelectedToolId(tool.tool_call_id);
    setEditArgsText(JSON.stringify(tool.tool_args, null, 2));
  };

  return (
    <div className="rounded-xl border border-[#222228] bg-[#111114] flex flex-col shadow-sm">
      {/* Panel Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-[#222228] bg-[#0d0d10] rounded-t-xl">
        <div className="flex items-center gap-2.5">
          <div className="flex h-6 w-6 items-center justify-center rounded-md bg-[#18181b] border border-[#27272a] text-zinc-300">
            <SlidersHorizontal className="h-3.5 w-3.5 text-zinc-400" />
          </div>
          <div className="flex items-center gap-2">
            <h2 className="text-xs font-semibold text-zinc-100 uppercase tracking-wider">
              Human-in-the-Loop C2 Governance
            </h2>
            {sessionId && (
              <span className="rounded bg-[#18181b] px-2 py-0.5 text-[10px] font-mono text-zinc-400 border border-[#27272a]">
                id: {sessionId.substring(0, 8)}
              </span>
            )}
          </div>
        </div>

        <div className="flex items-center gap-2">
          {auditLog && (
            <span
              className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-[10px] font-mono font-medium border ${
                auditLog.chain_verified
                  ? "border-emerald-500/25 bg-emerald-500/10 text-emerald-400"
                  : "border-rose-500/25 bg-rose-500/10 text-rose-400"
              }`}
            >
              <Lock className="h-3 w-3" />
              <span>SHA-256 Ledger: {auditLog.chain_verified ? "Verified" : "Tampered"}</span>
            </span>
          )}
          <span
            className={`rounded-full px-2.5 py-0.5 text-[10px] font-mono font-medium border ${
              pendingTools.length > 0
                ? "border-amber-500/25 bg-amber-500/10 text-amber-400"
                : "border-[#27272a] bg-[#141418] text-zinc-400"
            }`}
          >
            {pendingTools.length} Pending
          </span>
        </div>
      </div>

      {/* Worker Lease & Dead-Man's Switch Ribbon */}
      <div className="px-4 py-2 bg-[#0c0c0f] border-b border-[#1f1f26] flex flex-wrap items-center justify-between gap-3 text-xs">
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1.5 text-zinc-400">
            <Radio className="h-3.5 w-3.5 text-zinc-500" />
            <span className="font-mono text-zinc-300 text-[11px]">
              Worker Lease: {activeLease ? activeLease.worker_id : "No Active Lease"}
            </span>
          </div>

          {activeLease && (
            <span
              className={`inline-flex items-center gap-1 rounded px-2 py-0.5 font-mono text-[10px] border ${
                activeLease.is_expired
                  ? "border-rose-500/30 bg-rose-500/10 text-rose-400"
                  : "border-emerald-500/30 bg-emerald-500/10 text-emerald-400"
              }`}
            >
              <Timer className="h-3 w-3" />
              <span>
                {activeLease.is_expired
                  ? "EXPIRED"
                  : `TTL: ${Math.round(activeLease.ttl_remaining_seconds)}s remaining`}
              </span>
            </span>
          )}
        </div>

        {onReapLeases && (
          <button
            onClick={onReapLeases}
            className="flex items-center gap-1.5 rounded-md bg-[#18181b] hover:bg-[#222228] text-zinc-300 px-2.5 py-1 text-[11px] border border-[#27272a] transition-colors cursor-pointer"
            title="Trigger Dead-Man's Switch reaper sweep across expired sessions"
          >
            <Activity className="h-3 w-3 text-amber-400" />
            <span>Dead-Man&apos;s Reap</span>
          </button>
        )}
      </div>

      {/* Inline Status Notice if present */}
      {statusMessage && (
        <div className="mx-4 mt-3 flex items-center gap-2 rounded-lg border border-sky-500/25 bg-sky-500/10 px-3.5 py-2 text-xs text-sky-300">
          <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-sky-400" />
          <span className="font-mono text-[11px]">{statusMessage}</span>
        </div>
      )}

      {/* Dual Column Operations Workspace */}
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4 p-4">
        {/* Left Column: Intercepted MCP Tool Queue */}
        <div className="rounded-lg border border-[#222228] bg-[#131317] p-3.5 flex flex-col">
          <div className="flex items-center justify-between pb-2.5 mb-3 border-b border-[#1f1f26]">
            <span className="flex items-center gap-2 text-xs font-semibold text-zinc-100 uppercase tracking-wider">
              <ShieldAlert className="h-3.5 w-3.5 text-amber-400" />
              <span>Intercepted MCP Tool Calls</span>
            </span>
            <span className="text-[10px] font-mono text-zinc-500">Cryptographically Bound</span>
          </div>

          {pendingTools.length === 0 ? (
            <div className="flex-1 flex flex-col justify-between py-6">
              <div className="rounded-lg border border-dashed border-[#222228] bg-[#09090b]/50 p-6 text-center text-xs text-zinc-500">
                No tool calls currently awaiting human operator authorization.
              </div>

              {auditLog && auditLog.entries.length > 0 && (
                <div className="mt-4 pt-3 border-t border-[#1f1f26]">
                  <div className="text-[11px] font-mono text-zinc-400 mb-2">
                    Recent Compliance Audit Ledger
                  </div>
                  <div className="space-y-1.5 max-h-36 overflow-y-auto">
                    {auditLog.entries.slice(-3).map((entry) => (
                      <div
                        key={entry.audit_id}
                        className="rounded border border-[#222228] bg-[#09090b] px-2.5 py-1.5 text-xs flex items-center justify-between text-zinc-400 font-mono"
                      >
                        <span className="text-emerald-400 font-medium text-[11px]">
                          {entry.event_type}
                        </span>
                        <span className="text-zinc-500 text-[10px]">
                          #{entry.entry_hash.substring(0, 10)}...
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          ) : (
            <div className="space-y-3 flex-1 flex flex-col">
              {/* Tool selector pills */}
              <div className="flex flex-wrap gap-1.5">
                {pendingTools.map((t) => (
                  <button
                    key={t.tool_call_id}
                    onClick={() => handleToolSelect(t)}
                    className={`px-2.5 py-1 text-xs rounded-md font-mono border cursor-pointer transition-colors ${
                      currentTool?.tool_call_id === t.tool_call_id
                        ? "border-amber-500/40 bg-amber-500/10 text-amber-300 shadow-2xs"
                        : "border-[#222228] bg-[#09090b] text-zinc-400 hover:text-white"
                    }`}
                  >
                    {t.tool_name}
                  </button>
                ))}
              </div>

              {currentTool && (
                <div className="rounded-lg border border-[#222228] bg-[#09090b] p-3.5 space-y-3 flex-1 flex flex-col">
                  {/* Tool Meta Header */}
                  <div className="flex items-center justify-between pb-2 border-b border-[#1f1f26]">
                    <div>
                      <div className="text-xs font-semibold text-white font-mono">
                        {currentTool.tool_name}
                      </div>
                      {currentTool.is_destructive && (
                        <div className="text-[10px] text-rose-400 font-mono font-medium mt-0.5">
                          Destructive DDL/Filesystem Action
                        </div>
                      )}
                      {currentTool.security_risk && (
                        <div className="text-[10px] text-amber-400 font-mono mt-0.5">
                          Risk: {currentTool.security_risk}
                        </div>
                      )}
                    </div>
                    <span
                      className="text-[10px] font-mono text-zinc-500 hover:text-zinc-300 transition-colors"
                      title={currentTool.request_digest_sha256}
                    >
                      SHA:{" "}
                      {currentTool.request_digest_sha256
                        ? currentTool.request_digest_sha256.substring(0, 10)
                        : "N/A"}
                      ...
                    </span>
                  </div>

                  {/* Mode Selector Tabs */}
                  <div className="flex rounded-md bg-[#141418] p-0.5 border border-[#222228]">
                    {(
                      [
                        { id: "approve", label: "Authorize" },
                        { id: "edit", label: "Sanitize Args" },
                        { id: "mock", label: "Inject Mock" },
                        { id: "reject", label: "Reject" },
                      ] as const
                    ).map((m) => {
                      const isActive = mode === m.id;
                      return (
                        <button
                          key={m.id}
                          onClick={() => setMode(m.id)}
                          className={`flex-1 py-1 text-xs font-medium rounded transition-colors cursor-pointer ${
                            isActive
                              ? "bg-[#222228] text-white shadow-xs"
                              : "text-zinc-400 hover:text-zinc-200"
                          }`}
                        >
                          {m.label}
                        </button>
                      );
                    })}
                  </div>

                  {/* Action Input Body */}
                  <div className="flex-1">
                    {mode === "approve" && (
                      <div className="rounded border border-[#1f1f26] bg-[#111114] p-2.5">
                        <div className="text-[10px] text-zinc-400 mb-1 font-mono uppercase tracking-wider">
                          Arguments to Authorize:
                        </div>
                        <pre className="text-xs text-zinc-200 font-mono overflow-x-auto max-h-36">
                          {JSON.stringify(currentTool.tool_args, null, 2)}
                        </pre>
                      </div>
                    )}

                    {mode === "edit" && (
                      <div className="space-y-1">
                        <div className="text-[10px] text-zinc-400 font-mono uppercase tracking-wider">
                          Sanitize Tool Arguments (JSON):
                        </div>
                        <textarea
                          value={editArgsText || JSON.stringify(currentTool.tool_args, null, 2)}
                          onChange={(e) => setEditArgsText(e.target.value)}
                          className="w-full h-32 rounded border border-[#27272a] bg-[#111114] p-2.5 text-xs text-zinc-200 font-mono focus:outline-hidden focus:border-zinc-500 resize-none"
                        />
                      </div>
                    )}

                    {mode === "mock" && (
                      <div className="space-y-1">
                        <div className="text-[10px] text-zinc-400 font-mono uppercase tracking-wider">
                          Synthetic Fixture Output (JSON):
                        </div>
                        <textarea
                          value={mockOutputText}
                          onChange={(e) => setMockOutputText(e.target.value)}
                          className="w-full h-32 rounded border border-[#27272a] bg-[#111114] p-2.5 text-xs text-zinc-200 font-mono focus:outline-hidden focus:border-zinc-500 resize-none"
                        />
                      </div>
                    )}

                    {mode === "reject" && (
                      <div className="space-y-1">
                        <div className="text-[10px] text-zinc-400 font-mono uppercase tracking-wider">
                          Security Policy Rejection Reason:
                        </div>
                        <input
                          type="text"
                          value={rejectReason}
                          onChange={(e) => setRejectReason(e.target.value)}
                          className="w-full rounded border border-[#27272a] bg-[#111114] p-2 text-xs text-zinc-200 focus:outline-hidden focus:border-zinc-500"
                        />
                      </div>
                    )}
                  </div>

                  {/* Submit Action Trigger */}
                  <div className="pt-2 flex justify-end">
                    {mode === "approve" && (
                      <button
                        onClick={() => onApproveTool(currentTool.tool_call_id)}
                        className="flex items-center gap-1.5 rounded-md bg-emerald-500 hover:bg-emerald-400 text-zinc-950 font-semibold px-3 py-1.5 text-xs transition-colors cursor-pointer"
                      >
                        <Check className="h-3.5 w-3.5" />
                        <span>Authorize Execution</span>
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
                        className="flex items-center gap-1.5 rounded-md bg-amber-500 hover:bg-amber-400 text-zinc-950 font-semibold px-3 py-1.5 text-xs transition-colors cursor-pointer"
                      >
                        <Edit2 className="h-3.5 w-3.5" />
                        <span>Sanitize & Authorize</span>
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
                        className="flex items-center gap-1.5 rounded-md bg-sky-500 hover:bg-sky-400 text-zinc-950 font-semibold px-3 py-1.5 text-xs transition-colors cursor-pointer"
                      >
                        <Play className="h-3.5 w-3.5" />
                        <span>Inject Synthetic Output</span>
                      </button>
                    )}
                    {mode === "reject" && (
                      <button
                        onClick={() => onRejectTool(currentTool.tool_call_id, rejectReason)}
                        className="flex items-center gap-1.5 rounded-md bg-rose-500 hover:bg-rose-400 text-zinc-950 font-semibold px-3 py-1.5 text-xs transition-colors cursor-pointer"
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
        <div className="rounded-lg border border-[#222228] bg-[#131317] p-3.5 flex flex-col">
          <div className="flex items-center justify-between pb-2.5 mb-3 border-b border-[#1f1f26]">
            <span className="flex items-center gap-2 text-xs font-semibold text-zinc-100 uppercase tracking-wider">
              <FileCode className="h-3.5 w-3.5 text-emerald-400" />
              <span>RFC 6902 State Mutation</span>
            </span>
            <span className="text-[10px] text-zinc-500 font-mono">
              CP: {latestCheckpoint ? latestCheckpoint.checkpoint_id.substring(0, 8) : "None"}
            </span>
          </div>

          <div className="space-y-3 flex-1 flex flex-col">
            {latestCheckpoint ? (
              <div className="rounded border border-[#222228] bg-[#09090b] p-2.5">
                <div className="flex justify-between text-[10px] text-zinc-400 mb-1 font-mono">
                  <span>
                    State at Step #{latestCheckpoint.step_index} ({latestCheckpoint.node_name})
                  </span>
                  <span className="text-emerald-400 font-medium">Optimistic Lock Active</span>
                </div>
                <pre className="text-xs text-zinc-300 font-mono max-h-24 overflow-y-auto">
                  {JSON.stringify(latestCheckpoint.memory_state, null, 2)}
                </pre>
              </div>
            ) : (
              <div className="rounded border border-dashed border-[#222228] bg-[#09090b]/40 p-3 text-xs text-zinc-500">
                No checkpoint snapshot recorded on current session.
              </div>
            )}

            {/* Presets (Zero AI Sparkles) */}
            <div>
              <div className="text-[10px] text-zinc-400 mb-1.5 font-mono uppercase tracking-wider flex items-center gap-1.5">
                <Bookmark className="h-3 w-3 text-zinc-400" />
                <span>Patch Presets:</span>
              </div>
              <div className="flex flex-wrap gap-1.5">
                {PATCH_PRESETS.map((preset, i) => (
                  <button
                    key={i}
                    onClick={() => setJsonPatchText(preset.patch)}
                    className="rounded bg-[#18181b] hover:bg-[#222228] text-zinc-300 px-2 py-1 text-[11px] border border-[#27272a] transition-colors cursor-pointer"
                  >
                    {preset.label}
                  </button>
                ))}
              </div>
            </div>

            {/* Monaco-style Textarea */}
            <textarea
              value={jsonPatchText}
              onChange={(e) => setJsonPatchText(e.target.value)}
              className="flex-1 min-h-[120px] w-full rounded border border-[#27272a] bg-[#09090b] p-2.5 text-xs text-zinc-200 font-mono focus:outline-hidden focus:border-zinc-500 resize-none"
            />

            <div className="flex items-center justify-between pt-1">
              <span className="text-[11px] text-zinc-500 font-mono">
                Status: <strong className="text-zinc-200 font-medium">{sessionStatus || "None"}</strong>
              </span>

              <button
                disabled={!sessionId}
                onClick={() => onApplyPatch(jsonPatchText)}
                className="rounded-md bg-white hover:bg-zinc-200 text-zinc-950 px-3.5 py-1.5 text-xs font-semibold shadow-xs transition-all cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
              >
                Apply State Patch
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Cryptographic SHA-256 Audit Chain Section */}
      <div className="border-t border-[#222228]">
        <div className="flex items-center justify-between px-4 py-2.5 bg-[#0c0c0f]">
          <button
            onClick={() => setShowAuditChain(!showAuditChain)}
            className="flex items-center gap-2 text-xs font-semibold text-zinc-300 hover:text-white transition-colors cursor-pointer"
          >
            <Lock className="h-3.5 w-3.5 text-zinc-400" />
            <span className="font-mono text-xs">
              SHA-256 Audit Chain Ledger ({auditLog?.entries.length || 0} blocks)
            </span>
            {showAuditChain ? (
              <ChevronUp className="h-3.5 w-3.5 text-zinc-400" />
            ) : (
              <ChevronDown className="h-3.5 w-3.5 text-zinc-400" />
            )}
          </button>

          {auditLog && auditLog.entries.length > 0 && (
            <div className="flex items-center gap-2">
              <button
                onClick={() => handleExportAudit("json")}
                className="flex items-center gap-1 rounded bg-[#18181b] hover:bg-[#222228] text-zinc-300 px-2.5 py-1 text-[11px] font-mono border border-[#27272a] transition-colors cursor-pointer"
                title="Download JSON compliance attestation"
              >
                <Download className="h-3 w-3 text-zinc-400" />
                <span>Export JSON</span>
              </button>
              <button
                onClick={() => handleExportAudit("csv")}
                className="flex items-center gap-1 rounded bg-[#18181b] hover:bg-[#222228] text-zinc-300 px-2.5 py-1 text-[11px] font-mono border border-[#27272a] transition-colors cursor-pointer"
                title="Download CSV compliance table"
              >
                <Download className="h-3 w-3 text-zinc-400" />
                <span>Export CSV</span>
              </button>
            </div>
          )}
        </div>

        {showAuditChain && (
          <div className="px-4 py-3 border-t border-[#1f1f26] bg-[#09090b] space-y-2 max-h-80 overflow-y-auto">
            {auditLog?.verification_report && !auditLog.verification_report.is_valid && (
              <div className="flex items-start gap-2.5 p-3 rounded-lg border border-rose-500/30 bg-rose-500/10 text-xs text-rose-300">
                <AlertTriangle className="h-4 w-4 shrink-0 text-rose-400 mt-0.5" />
                <div>
                  <div className="font-semibold text-rose-200">
                    Cryptographic Integrity Violation: {auditLog.verification_report.violation_type}
                  </div>
                  <div className="text-[11px] text-rose-300 mt-0.5 font-mono">
                    {auditLog.verification_report.violation_details} (Tampered Block #
                    {auditLog.verification_report.tampered_entry_index})
                  </div>
                </div>
              </div>
            )}

            {auditLog && auditLog.entries.length > 0 ? (
              auditLog.entries.map((entry, idx) => (
                <div
                  key={entry.audit_id}
                  className="p-2.5 rounded border border-[#222228] bg-[#111114] font-mono text-[11px] space-y-1.5"
                >
                  <div className="flex items-center justify-between text-zinc-400">
                    <div className="flex items-center gap-2">
                      <span className="font-bold text-zinc-300">Block #{idx}</span>
                      <span className="rounded bg-[#1a1a20] px-1.5 py-0.5 text-zinc-200 font-sans text-[10px] font-medium border border-[#27272a]">
                        {entry.event_type}
                      </span>
                    </div>
                    <span className="text-[10px] text-zinc-500">
                      {new Date(entry.created_at).toLocaleTimeString()} by {entry.actor_id} (
                      {entry.actor_role})
                    </span>
                  </div>

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-2 text-[10px] text-zinc-400 pt-0.5">
                    <div className="flex items-center justify-between bg-[#09090b] px-2 py-1 rounded border border-[#1f1f26]">
                      <span className="text-zinc-500">Prev:</span>
                      <span className="text-zinc-400 font-mono">
                        {entry.prev_entry_hash.substring(0, 16)}...
                      </span>
                      <button
                        onClick={() => handleCopyHash(entry.prev_entry_hash)}
                        className="text-zinc-500 hover:text-white cursor-pointer ml-1"
                        title="Copy Prev Hash"
                      >
                        {copiedHash === entry.prev_entry_hash ? (
                          <Check className="h-3 w-3 text-emerald-400" />
                        ) : (
                          <Copy className="h-3 w-3" />
                        )}
                      </button>
                    </div>

                    <div className="flex items-center justify-between bg-[#09090b] px-2 py-1 rounded border border-[#1f1f26]">
                      <span className="text-zinc-500">Hash:</span>
                      <span className="text-emerald-400/90 font-mono">
                        {entry.entry_hash.substring(0, 16)}...
                      </span>
                      <button
                        onClick={() => handleCopyHash(entry.entry_hash)}
                        className="text-zinc-500 hover:text-white cursor-pointer ml-1"
                        title="Copy Block Hash"
                      >
                        {copiedHash === entry.entry_hash ? (
                          <Check className="h-3 w-3 text-emerald-400" />
                        ) : (
                          <Copy className="h-3 w-3" />
                        )}
                      </button>
                    </div>
                  </div>

                  {entry.payload && Object.keys(entry.payload).length > 0 && (
                    <div className="text-[10px] text-zinc-500 truncate pt-0.5">
                      payload: {JSON.stringify(entry.payload)}
                    </div>
                  )}
                </div>
              ))
            ) : (
              <div className="text-xs text-zinc-500 py-2">
                No audit log entries recorded yet for this session.
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
};
