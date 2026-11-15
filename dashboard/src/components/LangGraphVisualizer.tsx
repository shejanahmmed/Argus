import React, { useMemo, useState } from "react";
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
} from "lucide-react";
import { ArgusSpan } from "../types";

interface LangGraphVisualizerProps {
  spans: ArgusSpan[];
  selectedSpan: ArgusSpan | null;
  onSelectSpan: (span: ArgusSpan) => void;
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

  const sessionId = selectedSpan?.session_id || (spans.length > 0 ? spans[0].session_id : null);

  const handleExportPhoenix = async (format: "json" | "csv" = "json", evalType: string = "all") => {
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
    const xSpacing = 240;
    const ySpacing = 120;

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

      let kindColor = "bg-zinc-800 text-zinc-300 border-zinc-700";
      if (span.span_kind === "TOOL") {
        kindColor = "bg-sky-500/10 text-sky-400 border-sky-500/20";
      } else if (span.span_kind === "LLM") {
        kindColor = "bg-emerald-500/10 text-emerald-400 border-emerald-500/20";
      } else if (span.span_kind === "AGENT") {
        kindColor = "bg-purple-500/10 text-purple-400 border-purple-500/20";
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
                  ? "border-zinc-300 bg-zinc-800 shadow-lg ring-1 ring-zinc-400"
                  : isLoop
                  ? "border-rose-500/40 bg-zinc-900/90 hover:border-rose-400"
                  : "border-zinc-800 bg-zinc-900/80 hover:border-zinc-700 hover:bg-zinc-900"
              }`}
              style={{ width: 200 }}
            >
              <div className="flex items-center justify-between gap-1 mb-1.5">
                <span
                  className={`px-1.5 py-0.5 text-[10px] font-medium rounded border ${kindColor}`}
                >
                  #{index + 1} • {span.span_kind}
                </span>
                {isLoop ? (
                  <span className="px-1.5 py-0.5 text-[10px] bg-rose-500/10 text-rose-400 font-medium rounded border border-rose-500/20">
                    {span.attributes?.loop_tier ? `Tier ${span.attributes.loop_tier}` : "Loop"}
                  </span>
                ) : (
                  <span className="text-[11px] text-zinc-400 font-mono">
                    {span.latency_ms.toFixed(0)}ms
                  </span>
                )}
              </div>

              <div className="text-xs font-semibold text-zinc-100 truncate mb-1" title={displayLabel}>
                {displayLabel}
              </div>

              <div className="flex items-center justify-between text-[11px] text-zinc-400 pt-1 border-t border-zinc-800/60 font-mono">
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
            stroke: isLoop ? "#f43f5e" : "#52525b",
            strokeWidth: isLoop ? 1.8 : 1.4,
          },
          markerEnd: {
            type: MarkerType.ArrowClosed,
            color: isLoop ? "#f43f5e" : "#71717a",
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
        labelBgStyle: { fill: "#18181b", fillOpacity: 0.9 },
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
    <div className="rounded-xl border border-zinc-800 bg-[#121215] flex flex-col shadow-sm">
      {/* Visualizer Header */}
      <div className="flex items-center justify-between px-5 py-4 border-b border-zinc-800">
        <div className="flex items-center gap-3">
          <GitBranch className="h-4 w-4 text-zinc-400" />
          <h2 className="text-sm font-semibold text-zinc-100">Execution Topology</h2>
          {loopDetectedCount >= 3 && (
            <span className="inline-flex items-center gap-1 rounded-full bg-rose-500/10 px-2 py-0.5 text-xs font-medium text-rose-400 border border-rose-500/20">
              <AlertCircle className="h-3 w-3" />
              Loop Detected ({loopDetectedCount} steps)
            </span>
          )}
        </div>

        <div className="flex items-center gap-2">
          <span className="text-xs text-zinc-500 mr-1">{spans.length} spans</span>
          <div className="flex items-center rounded-lg bg-zinc-900 p-1 border border-zinc-800">
            <button
              onClick={() => setDisplayMode("DAG")}
              className={`flex items-center gap-1.5 rounded px-2.5 py-1 text-xs font-medium transition-colors cursor-pointer ${
                displayMode === "DAG"
                  ? "bg-zinc-800 text-white shadow-sm"
                  : "text-zinc-400 hover:text-zinc-200"
              }`}
            >
              <GitBranch className="h-3.5 w-3.5" />
              <span>Canvas</span>
            </button>
            <button
              onClick={() => setDisplayMode("WATERFALL")}
              className={`flex items-center gap-1.5 rounded px-2.5 py-1 text-xs font-medium transition-colors cursor-pointer ${
                displayMode === "WATERFALL"
                  ? "bg-zinc-800 text-white shadow-sm"
                  : "text-zinc-400 hover:text-zinc-200"
              }`}
            >
              <ListTree className="h-3.5 w-3.5" />
              <span>Waterfall</span>
            </button>
          </div>

          {sessionId && (
            <div className="relative">
              <button
                onClick={() => setShowExportMenu(!showExportMenu)}
                disabled={isExporting}
                className="flex items-center gap-1.5 rounded-lg border border-zinc-800 bg-zinc-900 px-2.5 py-1 text-xs font-medium text-zinc-300 hover:bg-zinc-800 hover:text-white transition-colors cursor-pointer disabled:opacity-50"
                title="Export Arize Phoenix & OpenInference Telemetry"
              >
                <Download className="h-3.5 w-3.5 text-orange-400" />
                <span>Export Phoenix</span>
              </button>

              {showExportMenu && (
                <div className="absolute right-0 top-full mt-1.5 w-52 rounded-lg border border-zinc-800 bg-[#121215] p-1.5 shadow-xl z-50">
                  <div className="px-2 py-1 text-[10px] font-semibold uppercase tracking-wider text-zinc-500 border-b border-zinc-800/80 mb-1">
                    Arize Phoenix OpenInference
                  </div>
                  <button
                    onClick={() => handleExportPhoenix("csv", "all")}
                    className="w-full flex items-center justify-between rounded px-2 py-1.5 text-xs text-left text-zinc-300 hover:bg-zinc-800 hover:text-white transition-colors cursor-pointer"
                  >
                    <span>DataFrame CSV</span>
                    <span className="text-[10px] font-mono text-zinc-500">.csv</span>
                  </button>
                  <button
                    onClick={() => handleExportPhoenix("json", "all")}
                    className="w-full flex items-center justify-between rounded px-2 py-1.5 text-xs text-left text-zinc-300 hover:bg-zinc-800 hover:text-white transition-colors cursor-pointer"
                  >
                    <span>OpenInference JSON</span>
                    <span className="text-[10px] font-mono text-zinc-500">.json</span>
                  </button>
                  <button
                    onClick={() => handleExportPhoenix("json", "hallucination")}
                    className="w-full flex items-center justify-between rounded px-2 py-1.5 text-xs text-left text-zinc-300 hover:bg-zinc-800 hover:text-white transition-colors cursor-pointer"
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
        <div className="flex h-[320px] items-center justify-center text-xs text-zinc-500">
          Select an agent session to inspect execution graph and telemetry traces
        </div>
      ) : displayMode === "DAG" ? (
        <div className="relative h-[340px] w-full bg-[#0c0c0e]">
          <div className="absolute inset-0">
            <ReactFlow
              key={flowKey}
              nodes={nodes}
              edges={edges}
              fitView
              fitViewOptions={{ padding: 0.2 }}
              minZoom={0.4}
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
        <div className="h-[340px] overflow-y-auto p-4 space-y-2 bg-[#0c0c0e]">
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
                    ? "border-zinc-500 bg-zinc-800/80"
                    : "border-zinc-800/80 bg-zinc-900/40 hover:border-zinc-700"
                }`}
              >
                <div className="flex items-center justify-between gap-2 text-xs mb-1.5">
                  <div className="flex items-center gap-2">
                    <span className="text-[11px] text-zinc-500">#{idx + 1}</span>
                    <span className="rounded bg-zinc-800 px-1.5 py-0.5 text-[10px] font-medium text-zinc-300">
                      {span.span_kind}
                    </span>
                    <span className="font-medium text-zinc-100">
                      {toolName ? `${span.name} (${toolName})` : span.name}
                    </span>
                    {span.redacted && (
                      <span className="inline-flex items-center gap-1 rounded bg-amber-500/10 px-1.5 py-0.5 text-[10px] text-amber-400 border border-amber-500/20">
                        <ShieldCheck className="h-3 w-3" />
                        PII Redacted
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-3 text-xs text-zinc-400 font-mono">
                    <span>{span.latency_ms.toFixed(1)}ms</span>
                    <span className="text-zinc-200">${span.cost_usd.toFixed(4)}</span>
                  </div>
                </div>
                <div className="h-1.5 w-full rounded-full bg-zinc-800 overflow-hidden">
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
        <div className="border-t border-zinc-800 bg-[#0e0e11] p-4 text-xs">
          <div className="flex items-center justify-between pb-3 mb-3 border-b border-zinc-800">
            <div className="flex items-center gap-2.5">
              <Code2 className="h-4 w-4 text-zinc-400" />
              <span className="font-semibold text-white">
                Span: {selectedSpan.name}
              </span>
              <span className="rounded bg-zinc-800 px-2 py-0.5 text-[11px] font-medium text-zinc-400 border border-zinc-700">
                {selectedSpan.span_kind} • {selectedSpan.operation_name}
              </span>
            </div>

            <div className="flex items-center rounded-lg bg-zinc-900 p-0.5 border border-zinc-800">
              <button
                onClick={() => setInspectorTab("PAYLOADS")}
                className={`rounded px-2.5 py-1 text-xs font-medium cursor-pointer ${
                  inspectorTab === "PAYLOADS"
                    ? "bg-zinc-800 text-white"
                    : "text-zinc-400 hover:text-zinc-200"
                }`}
              >
                Payloads
              </button>
              <button
                onClick={() => setInspectorTab("ATTRIBUTES")}
                className={`rounded px-2.5 py-1 text-xs font-medium cursor-pointer ${
                  inspectorTab === "ATTRIBUTES"
                    ? "bg-zinc-800 text-white"
                    : "text-zinc-400 hover:text-zinc-200"
                }`}
              >
                Attributes & OTel
              </button>
            </div>
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-3">
            <div className="rounded-lg border border-zinc-800 bg-zinc-900/60 p-2.5">
              <div className="text-zinc-400 flex items-center gap-1 text-[11px] mb-0.5">
                <DollarSign className="h-3 w-3 text-emerald-400" /> Cost
              </div>
              <div className="text-zinc-100 font-mono font-medium">
                ${selectedSpan.cost_usd.toFixed(5)}
              </div>
            </div>
            <div className="rounded-lg border border-zinc-800 bg-zinc-900/60 p-2.5">
              <div className="text-zinc-400 flex items-center gap-1 text-[11px] mb-0.5">
                <Clock className="h-3 w-3 text-sky-400" /> Duration
              </div>
              <div className="text-zinc-100 font-mono font-medium">
                {selectedSpan.latency_ms.toFixed(1)} ms
              </div>
            </div>
            <div className="rounded-lg border border-zinc-800 bg-zinc-900/60 p-2.5">
              <div className="text-zinc-400 flex items-center gap-1 text-[11px] mb-0.5">
                <Cpu className="h-3 w-3 text-amber-400" /> Prompt Tokens
              </div>
              <div className="text-zinc-100 font-mono font-medium">
                {selectedSpan.prompt_tokens}
              </div>
            </div>
            <div className="rounded-lg border border-zinc-800 bg-zinc-900/60 p-2.5">
              <div className="text-zinc-400 flex items-center gap-1 text-[11px] mb-0.5">
                <Cpu className="h-3 w-3 text-purple-400" /> Output Tokens
              </div>
              <div className="text-zinc-100 font-mono font-medium">
                {selectedSpan.completion_tokens}
              </div>
            </div>
          </div>

          {inspectorTab === "PAYLOADS" ? (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs">
              <div className="rounded-lg border border-zinc-800 bg-zinc-950 p-3">
                <div className="text-[11px] font-medium text-zinc-400 mb-1.5">
                  Input Payload (Edge Sanitized)
                </div>
                <pre className="text-zinc-300 font-mono text-[11px] overflow-x-auto max-h-24">
                  {JSON.stringify(selectedSpan.input_payload, null, 2)}
                </pre>
              </div>
              <div className="rounded-lg border border-zinc-800 bg-zinc-950 p-3">
                <div className="text-[11px] font-medium text-zinc-400 mb-1.5">
                  Output Payload
                </div>
                <pre className="text-zinc-300 font-mono text-[11px] overflow-x-auto max-h-24">
                  {JSON.stringify(selectedSpan.output_payload, null, 2)}
                </pre>
              </div>
            </div>
          ) : (
            <div className="rounded-lg border border-zinc-800 bg-zinc-950 p-3 text-xs space-y-1.5 font-mono">
              <div className="flex justify-between">
                <span className="text-zinc-500">Span ID (UUIDv7):</span>
                <span className="text-zinc-300">{selectedSpan.span_id}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-zinc-500">Dotted Order Hierarchy:</span>
                <span className="text-sky-400 truncate max-w-[400px]">{selectedSpan.dotted_order}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-zinc-500">Attributes:</span>
                <span className="text-zinc-300 truncate max-w-[400px]">
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
