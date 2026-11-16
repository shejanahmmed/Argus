import React, { useMemo, useState, useRef, useEffect } from "react";
import {
  ReactFlow,
  Controls,
  Background,
  BackgroundVariant,
  Node,
  Edge,
  MarkerType,
} from "@xyflow/react";
import {
  GitBranch,
  ListTree,
  AlertCircle,
  Clock,
  DollarSign,
  Cpu,
  ShieldCheck,
  Code2,
  Download,
  X,
  Copy,
  Check,
  ChevronDown,
} from "lucide-react";
import { ArgusSpan } from "../types";

interface LangGraphVisualizerProps {
  spans: ArgusSpan[];
  selectedSpan: ArgusSpan | null;
  onSelectSpan: (span: ArgusSpan | null) => void;
  authFetch?: (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;
}

export const LangGraphVisualizer: React.FC<LangGraphVisualizerProps> = ({
  spans,
  selectedSpan,
  onSelectSpan,
  authFetch,
}) => {
  const [displayMode, setDisplayMode] = useState<"DAG" | "WATERFALL">("DAG");
  const [inspectorTab, setInspectorTab] = useState<"PAYLOADS" | "ATTRIBUTES">("PAYLOADS");
  const [isExporting, setIsExporting] = useState<boolean>(false);
  const [showExportMenu, setShowExportMenu] = useState<boolean>(false);
  const [copiedField, setCopiedField] = useState<"input" | "output" | null>(null);

  const exportMenuRef = useRef<HTMLDivElement>(null);
  const sessionId = selectedSpan?.session_id || (spans.length > 0 ? spans[0].session_id : null);

  // Close export dropdown on click outside
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (
        exportMenuRef.current &&
        !exportMenuRef.current.contains(e.target as unknown as HTMLElement)
      ) {
        setShowExportMenu(false);
      }
    };
    if (showExportMenu) {
      document.addEventListener("mousedown", handleClickOutside);
      return () => document.removeEventListener("mousedown", handleClickOutside);
    }
  }, [showExportMenu]);

  const handleCopyPayload = (field: "input" | "output", payload: unknown) => {
    try {
      navigator.clipboard.writeText(JSON.stringify(payload, null, 2));
      setCopiedField(field);
      setTimeout(() => setCopiedField(null), 2000);
    } catch (err) {
      console.error("Failed to copy payload to clipboard:", err);
    }
  };

  const handleExportPhoenix = async (
    format: "json" | "csv" = "json",
    evalType: string = "all"
  ) => {
    if (!sessionId) return;
    setIsExporting(true);
    try {
      const fetchFn = authFetch || fetch;
      const res = await fetchFn(
        `/api/v1/telemetry/sessions/${sessionId}/phoenix?format=${format}&eval_type=${evalType}`
      );
      if (res.ok) {
        const blob = await res.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download =
          format === "csv"
            ? `phoenix_spans_${sessionId}.csv`
            : `phoenix_openinference_${sessionId}.json`;
        a.click();
        window.URL.revokeObjectURL(url);
      }
    } catch (err) {
      console.error("Failed to export Phoenix OpenInference data:", err);
    } finally {
      setIsExporting(false);
      setShowExportMenu(false);
    }
  };

  const { nodes, edges, loopDetectedCount } = useMemo(() => {
    if (spans.length === 0) {
      return { nodes: [], edges: [], loopDetectedCount: 0 };
    }

    const calculatedNodes: Node[] = [];
    const calculatedEdges: Edge[] = [];
    const xSpacing = 260;
    const ySpacing = 130;

    const nameCount: Record<string, number> = {};
    spans.forEach((s) => {
      const key = (s.attributes?.tool_name as string) || s.name;
      nameCount[key] = (nameCount[key] || 0) + 1;
    });

    let loopSpansCount = 0;
    let firstLoopSpanId: string | null = null;
    let lastLoopSpanId: string | null = null;

    spans.forEach((span, index) => {
      const toolName = span.attributes?.tool_name as string | undefined;
      const rawKey = toolName || span.name;
      const displayLabel = toolName ? `Tool: ${toolName}` : span.name;
      const loopTrippedAttr = span.attributes?.loop_tripped === "true";
      const isLoop = loopTrippedAttr || (nameCount[rawKey] || 0) >= 3;
      const isSelected = selectedSpan?.span_id === span.span_id;

      if (isLoop) {
        loopSpansCount += 1;
        if (!firstLoopSpanId) firstLoopSpanId = span.span_id;
        lastLoopSpanId = span.span_id;
      }

      const col = index % 3;
      const row = Math.floor(index / 3);
      const posX = 40 + col * xSpacing;
      const posY = 35 + row * ySpacing;

      let kindColor = "bg-[#18181b] text-zinc-300 border-[#27272a]";
      if (span.span_kind === "TOOL") {
        kindColor = "bg-sky-500/10 text-sky-400 border-sky-500/25";
      } else if (span.span_kind === "LLM") {
        kindColor = "bg-emerald-500/10 text-emerald-400 border-emerald-500/25";
      } else if (span.span_kind === "AGENT") {
        kindColor = "bg-indigo-500/10 text-indigo-400 border-indigo-500/25";
      }

      calculatedNodes.push({
        id: span.span_id,
        position: { x: posX, y: posY },
        data: {
          label: (
            <div
              onClick={() => onSelectSpan(span)}
              className={`rounded-lg border p-3 font-sans text-left cursor-pointer transition-all ${
                isSelected
                  ? "border-zinc-300 bg-[#18181f] shadow-lg ring-1 ring-zinc-400"
                  : isLoop
                  ? "border-rose-500/50 bg-[#141013] hover:border-rose-400"
                  : "border-[#222228] bg-[#121215] hover:border-[#2e2e38] hover:bg-[#16161b]"
              }`}
              style={{ width: 220 }}
            >
              <div className="flex items-center justify-between gap-1 mb-1.5">
                <span
                  className={`px-1.5 py-0.5 text-[9px] font-mono font-medium rounded border ${kindColor}`}
                >
                  #{index + 1} • {span.span_kind}
                </span>
                {isLoop ? (
                  <span className="px-1.5 py-0.5 text-[9px] bg-rose-500/10 text-rose-400 font-mono font-medium rounded border border-rose-500/25">
                    {span.attributes?.loop_tier ? `Tier ${span.attributes.loop_tier}` : "Loop"}
                  </span>
                ) : (
                  <span className="text-[10px] text-zinc-500 font-mono">
                    {span.latency_ms.toFixed(0)}ms
                  </span>
                )}
              </div>

              <div
                className="text-xs font-medium text-zinc-100 truncate mb-1"
                title={displayLabel}
              >
                {displayLabel}
              </div>

              <div className="flex items-center justify-between text-[10px] text-zinc-400 pt-1.5 border-t border-[#1f1f26] font-mono">
                <span>
                  {span.prompt_tokens + span.completion_tokens > 0
                    ? `${span.prompt_tokens + span.completion_tokens} tok`
                    : span.operation_name}
                </span>
                <span className="text-zinc-200 font-medium">
                  ${span.cost_usd.toFixed(4)}
                </span>
              </div>
            </div>
          ),
        },
      });

      if (index > 0) {
        const prevSpan = spans[index - 1];
        calculatedEdges.push({
          id: `e-${prevSpan.span_id}-${span.span_id}`,
          source: prevSpan.span_id,
          target: span.span_id,
          animated: true,
          style: {
            stroke: isLoop ? "#f43f5e" : "#3f3f46",
            strokeWidth: isLoop ? 1.8 : 1.2,
          },
          markerEnd: {
            type: MarkerType.ArrowClosed,
            color: isLoop ? "#f43f5e" : "#52525b",
          },
        });
      }
    });

    if (firstLoopSpanId && lastLoopSpanId && firstLoopSpanId !== lastLoopSpanId) {
      calculatedEdges.push({
        id: `cycle-${lastLoopSpanId}-${firstLoopSpanId}`,
        source: lastLoopSpanId,
        target: firstLoopSpanId,
        animated: true,
        label: "Loop Cycle",
        labelStyle: { fill: "#f43f5e", fontWeight: 600, fontSize: 10 },
        labelBgStyle: { fill: "#111114", fillOpacity: 0.9 },
        style: {
          stroke: "#f43f5e",
          strokeWidth: 1.8,
          strokeDasharray: "4 4",
        },
        markerEnd: {
          type: MarkerType.ArrowClosed,
          color: "#f43f5e",
        },
      });
    }

    return {
      nodes: calculatedNodes,
      edges: calculatedEdges,
      loopDetectedCount: loopSpansCount,
    };
  }, [spans, selectedSpan, onSelectSpan]);

  const maxLatency = useMemo(
    () => Math.max(10, ...spans.map((s) => s.latency_ms)),
    [spans]
  );

  const flowKey = useMemo(
    () => spans.map((s) => s.span_id).join("-") || "empty",
    [spans]
  );

  return (
    <div className="rounded-xl border border-[#222228] bg-[#111114] flex flex-col shadow-sm overflow-hidden">
      {/* Panel Header */}
      <div className="flex flex-wrap items-center justify-between px-4 py-3 border-b border-[#222228] bg-[#0d0d10] rounded-t-xl gap-2.5">
        <div className="flex items-center gap-2.5 min-w-0">
          <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-[#18181b] border border-[#27272a] text-zinc-300">
            <GitBranch className="h-3.5 w-3.5 text-zinc-400" />
          </div>
          <div className="flex items-center gap-2 min-w-0">
            <h2 className="text-xs font-semibold text-zinc-100 uppercase tracking-wider whitespace-nowrap">
              Execution Topology
            </h2>
            <span className="rounded-md bg-[#18181b] px-2 py-0.5 text-[10px] font-mono font-medium text-zinc-400 border border-[#27272a] whitespace-nowrap shrink-0">
              {spans.length} spans
            </span>
          </div>
          {loopDetectedCount >= 3 && (
            <span className="inline-flex items-center gap-1 rounded-md bg-rose-500/10 px-2 py-0.5 text-[10px] font-mono font-medium text-rose-400 border border-rose-500/20 whitespace-nowrap shrink-0">
              <AlertCircle className="h-3 w-3 shrink-0" />
              Loop Detected ({loopDetectedCount} steps)
            </span>
          )}
        </div>

        <div className="flex items-center gap-2 shrink-0">
          {/* View Mode Toggle */}
          <div className="flex items-center rounded-md bg-[#141418] p-0.5 border border-[#222228]">
            <button
              onClick={() => setDisplayMode("DAG")}
              className={`flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-medium transition-colors cursor-pointer whitespace-nowrap shrink-0 ${
                displayMode === "DAG"
                  ? "bg-[#222228] text-white shadow-xs"
                  : "text-zinc-400 hover:text-zinc-200"
              }`}
            >
              <GitBranch className="h-3 w-3" />
              <span>Canvas</span>
            </button>
            <button
              onClick={() => setDisplayMode("WATERFALL")}
              className={`flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-medium transition-colors cursor-pointer whitespace-nowrap shrink-0 ${
                displayMode === "WATERFALL"
                  ? "bg-[#222228] text-white shadow-xs"
                  : "text-zinc-400 hover:text-zinc-200"
              }`}
            >
              <ListTree className="h-3 w-3" />
              <span>Waterfall</span>
            </button>
          </div>

          {/* Export Phoenix Popover */}
          {sessionId && (
            <div className="relative" ref={exportMenuRef}>
              <button
                onClick={() => setShowExportMenu((prev) => !prev)}
                disabled={isExporting}
                className="flex items-center gap-1.5 rounded-md border border-[#222228] bg-[#141418] px-2.5 py-1 text-xs font-medium text-zinc-300 hover:bg-[#1a1a20] hover:text-white transition-colors cursor-pointer disabled:opacity-50 whitespace-nowrap shrink-0"
                title="Export Arize Phoenix & OpenInference Telemetry"
              >
                <Download className="h-3 w-3 text-orange-400" />
                <span>Export Phoenix</span>
                <ChevronDown
                  className={`h-3 w-3 text-zinc-500 transition-transform ${
                    showExportMenu ? "rotate-180" : ""
                  }`}
                />
              </button>

              {showExportMenu && (
                <div className="absolute right-0 top-full mt-1.5 w-56 rounded-lg border border-[#27272a] bg-[#121215] p-1.5 shadow-2xl z-50 animate-in fade-in zoom-in-95">
                  <div className="px-2 py-1 text-[10px] font-semibold uppercase tracking-wider text-zinc-500 border-b border-[#222228] mb-1">
                    Arize Phoenix OpenInference
                  </div>
                  <button
                    onClick={() => handleExportPhoenix("csv", "all")}
                    className="w-full flex items-center justify-between rounded px-2 py-1.5 text-xs text-left text-zinc-300 hover:bg-[#1a1a20] hover:text-white transition-colors cursor-pointer"
                  >
                    <span>DataFrame CSV</span>
                    <span className="text-[10px] font-mono text-zinc-500">.csv</span>
                  </button>
                  <button
                    onClick={() => handleExportPhoenix("json", "all")}
                    className="w-full flex items-center justify-between rounded px-2 py-1.5 text-xs text-left text-zinc-300 hover:bg-[#1a1a20] hover:text-white transition-colors cursor-pointer"
                  >
                    <span>OpenInference JSON</span>
                    <span className="text-[10px] font-mono text-zinc-500">.json</span>
                  </button>
                  <button
                    onClick={() => handleExportPhoenix("json", "hallucination")}
                    className="w-full flex items-center justify-between rounded px-2 py-1.5 text-xs text-left text-zinc-300 hover:bg-[#1a1a20] hover:text-white transition-colors cursor-pointer"
                  >
                    <span>Eval Datasets (Q&A/Tools)</span>
                    <span className="text-[10px] font-mono text-amber-500">evals</span>
                  </button>
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Main Canvas Viewport */}
      {spans.length === 0 ? (
        <div className="flex h-[420px] items-center justify-center text-xs text-zinc-500">
          Select an agent session to inspect execution graph and telemetry traces
        </div>
      ) : displayMode === "DAG" ? (
        <div className="relative h-[420px] w-full bg-[#09090b]">
          <div className="absolute inset-0">
            <ReactFlow
              key={flowKey}
              nodes={nodes}
              edges={edges}
              fitView
              fitViewOptions={{ padding: 0.2 }}
              minZoom={0.3}
              maxZoom={1.5}
            >
              <Background
                variant={BackgroundVariant.Dots}
                gap={18}
                size={1}
                color="rgba(255, 255, 255, 0.08)"
              />
              <Controls />
            </ReactFlow>
          </div>
        </div>
      ) : (
        <div className="h-[420px] overflow-y-auto p-4 space-y-2 bg-[#09090b]">
          {spans.map((span, idx) => {
            const isSelected = selectedSpan?.span_id === span.span_id;
            const depth = Math.max(0, (span.dotted_order.match(/\./g) || []).length);
            const widthPct = Math.max(5, (span.latency_ms / maxLatency) * 100);
            const toolName = span.attributes?.tool_name as string | undefined;

            return (
              <div
                key={span.span_id}
                onClick={() => onSelectSpan(span)}
                style={{ marginLeft: `${Math.min(depth * 16, 64)}px` }}
                className={`rounded-lg border p-3 cursor-pointer transition-all ${
                  isSelected
                    ? "border-zinc-400 bg-[#18181f] shadow-sm"
                    : "border-[#222228] bg-[#121215] hover:border-[#2e2e38] hover:bg-[#16161b]"
                }`}
              >
                <div className="flex flex-wrap items-center justify-between gap-2 text-xs mb-1.5">
                  <div className="flex flex-wrap items-center gap-2 min-w-0">
                    <span className="text-[10px] text-zinc-500 font-mono whitespace-nowrap">#{idx + 1}</span>
                    <span className="rounded-md bg-[#1a1a20] px-1.5 py-0.5 text-[9px] font-mono font-medium text-zinc-300 border border-[#27272a] whitespace-nowrap shrink-0">
                      {span.span_kind}
                    </span>
                    <span className="font-medium text-zinc-100 text-xs truncate">
                      {toolName ? `${span.name} (${toolName})` : span.name}
                    </span>
                    {span.redacted && (
                      <span className="inline-flex items-center gap-1 rounded-md bg-amber-500/10 px-1.5 py-0.5 text-[9px] font-mono text-amber-400 border border-amber-500/20 whitespace-nowrap shrink-0">
                        <ShieldCheck className="h-3 w-3 shrink-0" />
                        PII Redacted
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-3 text-xs text-zinc-400 font-mono whitespace-nowrap shrink-0">
                    <span>{span.latency_ms.toFixed(1)}ms</span>
                    <span className="text-zinc-200">${span.cost_usd.toFixed(4)}</span>
                  </div>
                </div>
                <div className="h-1 w-full rounded-full bg-[#1e1e24] overflow-hidden">
                  <div
                    className="h-full rounded-full bg-sky-500"
                    style={{ width: `${widthPct}%` }}
                  />
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Selected Span Inspector Drawer */}
      {selectedSpan && (
        <div className="border-t border-[#222228] bg-[#0d0d10] p-4 text-xs">
          {/* Inspector Header */}
          <div className="flex flex-wrap items-center justify-between pb-3 mb-3 border-b border-[#222228] gap-2">
            <div className="flex flex-wrap items-center gap-2.5 min-w-0">
              <div className="flex h-5 w-5 shrink-0 items-center justify-center rounded-md bg-[#18181b] border border-[#27272a] text-zinc-300">
                <Code2 className="h-3 w-3 text-zinc-400" />
              </div>
              <span className="font-medium text-white text-xs truncate">
                Span: {selectedSpan.name}
              </span>
              <span className="rounded-md bg-[#1a1a20] px-2 py-0.5 text-[10px] font-mono font-medium text-zinc-400 border border-[#27272a] whitespace-nowrap shrink-0">
                {selectedSpan.span_kind} • {selectedSpan.operation_name}
              </span>
            </div>

            <div className="flex items-center gap-2 shrink-0">
              <div className="flex items-center rounded-md bg-[#141418] p-0.5 border border-[#222228]">
                <button
                  onClick={() => setInspectorTab("PAYLOADS")}
                  className={`rounded-md px-2.5 py-1 text-xs font-medium cursor-pointer transition-colors whitespace-nowrap shrink-0 ${
                    inspectorTab === "PAYLOADS"
                      ? "bg-[#222228] text-white"
                      : "text-zinc-400 hover:text-zinc-200"
                  }`}
                >
                  Payloads
                </button>
                <button
                  onClick={() => setInspectorTab("ATTRIBUTES")}
                  className={`rounded-md px-2.5 py-1 text-xs font-medium cursor-pointer transition-colors whitespace-nowrap shrink-0 ${
                    inspectorTab === "ATTRIBUTES"
                      ? "bg-[#222228] text-white"
                      : "text-zinc-400 hover:text-zinc-200"
                  }`}
                >
                  Attributes & OTel
                </button>
              </div>

              {/* Dismiss Button */}
              <button
                onClick={() => onSelectSpan(null)}
                className="rounded-md p-1 text-zinc-400 hover:text-white hover:bg-[#1a1a20] transition-colors cursor-pointer shrink-0"
                title="Dismiss inspector"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </div>
          </div>

          {/* Quick Metrics Tiles */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5 mb-3">
            <div className="rounded-lg border border-[#222228] bg-[#141418] p-2.5">
              <div className="text-zinc-400 flex items-center gap-1 text-[10px] mb-0.5 font-mono whitespace-nowrap">
                <DollarSign className="h-3 w-3 text-emerald-400 shrink-0" /> Spend USD
              </div>
              <div className="text-zinc-100 font-mono font-semibold text-xs whitespace-nowrap">
                ${selectedSpan.cost_usd.toFixed(5)}
              </div>
            </div>
            <div className="rounded-lg border border-[#222228] bg-[#141418] p-2.5">
              <div className="text-zinc-400 flex items-center gap-1 text-[10px] mb-0.5 font-mono whitespace-nowrap">
                <Clock className="h-3 w-3 text-sky-400 shrink-0" /> Latency
              </div>
              <div className="text-zinc-100 font-mono font-semibold text-xs whitespace-nowrap">
                {selectedSpan.latency_ms.toFixed(1)} ms
              </div>
            </div>
            <div className="rounded-lg border border-[#222228] bg-[#141418] p-2.5">
              <div className="text-zinc-400 flex items-center gap-1 text-[10px] mb-0.5 font-mono whitespace-nowrap">
                <Cpu className="h-3 w-3 text-amber-400 shrink-0" /> Prompt Tokens
              </div>
              <div className="text-zinc-100 font-mono font-semibold text-xs whitespace-nowrap">
                {selectedSpan.prompt_tokens}
              </div>
            </div>
            <div className="rounded-lg border border-[#222228] bg-[#141418] p-2.5">
              <div className="text-zinc-400 flex items-center gap-1 text-[10px] mb-0.5 font-mono whitespace-nowrap">
                <Cpu className="h-3 w-3 text-purple-400 shrink-0" /> Completion Tokens
              </div>
              <div className="text-zinc-100 font-mono font-semibold text-xs whitespace-nowrap">
                {selectedSpan.completion_tokens}
              </div>
            </div>
          </div>

          {/* Tab Content */}
          {inspectorTab === "PAYLOADS" ? (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs">
              {/* Input Payload */}
              <div className="rounded-lg border border-[#222228] bg-[#09090b] p-3">
                <div className="flex items-center justify-between mb-1.5">
                  <span className="text-[10px] font-mono text-zinc-400 uppercase tracking-wider">
                    Input Payload (Edge Sanitized)
                  </span>
                  <button
                    onClick={() => handleCopyPayload("input", selectedSpan.input_payload)}
                    className="flex items-center gap-1 text-[10px] text-zinc-400 hover:text-white transition-colors cursor-pointer"
                  >
                    {copiedField === "input" ? (
                      <>
                        <Check className="h-3 w-3 text-emerald-400" />
                        <span className="text-emerald-400 font-mono">Copied</span>
                      </>
                    ) : (
                      <>
                        <Copy className="h-3 w-3" />
                        <span className="font-mono">Copy</span>
                      </>
                    )}
                  </button>
                </div>
                <pre className="text-zinc-300 font-mono text-[11px] overflow-x-auto max-h-28 p-2 rounded bg-[#111114] border border-[#1f1f26]">
                  {JSON.stringify(selectedSpan.input_payload, null, 2)}
                </pre>
              </div>

              {/* Output Payload */}
              <div className="rounded-lg border border-[#222228] bg-[#09090b] p-3">
                <div className="flex items-center justify-between mb-1.5">
                  <span className="text-[10px] font-mono text-zinc-400 uppercase tracking-wider">
                    Output Payload
                  </span>
                  <button
                    onClick={() => handleCopyPayload("output", selectedSpan.output_payload)}
                    className="flex items-center gap-1 text-[10px] text-zinc-400 hover:text-white transition-colors cursor-pointer"
                  >
                    {copiedField === "output" ? (
                      <>
                        <Check className="h-3 w-3 text-emerald-400" />
                        <span className="text-emerald-400 font-mono">Copied</span>
                      </>
                    ) : (
                      <>
                        <Copy className="h-3 w-3" />
                        <span className="font-mono">Copy</span>
                      </>
                    )}
                  </button>
                </div>
                <pre className="text-zinc-300 font-mono text-[11px] overflow-x-auto max-h-28 p-2 rounded bg-[#111114] border border-[#1f1f26]">
                  {JSON.stringify(selectedSpan.output_payload, null, 2)}
                </pre>
              </div>
            </div>
          ) : (
            <div className="rounded-lg border border-[#222228] bg-[#09090b] p-3 text-xs space-y-1.5 font-mono">
              <div className="flex justify-between border-b border-[#1f1f26] pb-1">
                <span className="text-zinc-500">Span ID (UUIDv7):</span>
                <span className="text-zinc-200">{selectedSpan.span_id}</span>
              </div>
              <div className="flex justify-between border-b border-[#1f1f26] pb-1">
                <span className="text-zinc-500">Dotted Order Hierarchy:</span>
                <span className="text-sky-400 truncate max-w-[420px]">
                  {selectedSpan.dotted_order}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-zinc-500">OTel Attributes:</span>
                <span className="text-zinc-300 truncate max-w-[420px]">
                  {JSON.stringify(selectedSpan.attributes)}
                </span>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
};
