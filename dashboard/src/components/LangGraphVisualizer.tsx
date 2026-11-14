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
  AlertOctagon,
  Clock,
  Coins,
  Cpu,
  Shield,
  Code2,
} from "lucide-react";
import { ArgusSpan } from "../types";

interface LangGraphVisualizerProps {
  spans: ArgusSpan[];
  selectedSpan: ArgusSpan | null;
  onSelectSpan: (span: ArgusSpan) => void;
}

export const LangGraphVisualizer: React.FC<LangGraphVisualizerProps> = ({
  spans,
  selectedSpan,
  onSelectSpan,
}) => {
  const [displayMode, setDisplayMode] = useState<"DAG" | "WATERFALL">("DAG");
  const [inspectorTab, setInspectorTab] = useState<"PAYLOADS" | "ATTRIBUTES">("PAYLOADS");

  const { nodes, edges, loopDetectedCount } = useMemo(() => {
    if (spans.length === 0) {
      return { nodes: [], edges: [], loopDetectedCount: 0 };
    }

    const calculatedNodes: Node[] = [];
    const calculatedEdges: Edge[] = [];
    const xSpacing = 250;
    const ySpacing = 125;

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
      const displayLabel = toolName ? `TOOL // ${toolName}` : span.name;
      const isLoop = (nameCount[rawKey] || 0) >= 3;
      const isSelected = selectedSpan?.span_id === span.span_id;

      if (isLoop) {
        loopSpansCount += 1;
        if (!firstLoopSpanId) firstLoopSpanId = span.span_id;
        lastLoopSpanId = span.span_id;
      }

      const col = index % 3;
      const row = Math.floor(index / 3);
      const posX = 36 + col * xSpacing;
      const posY = 36 + row * ySpacing;

      let borderColor = "#2e2e2e";
      let accentColor = "#e5e5e5";
      let badgeBg = "#141414";
      let cardBg = "#070707";

      if (isLoop) {
        borderColor = "#ff3333";
        accentColor = "#ff5555";
        badgeBg = "#2b0404";
        cardBg = "#160303";
      } else if (span.span_kind === "TOOL") {
        borderColor = "#00e5ff";
        accentColor = "#00e5ff";
        badgeBg = "#002229";
        cardBg = "#031014";
      } else if (span.span_kind === "LLM") {
        borderColor = "#00ff66";
        accentColor = "#00ff66";
        badgeBg = "#00240e";
        cardBg = "#031208";
      } else if (span.span_kind === "AGENT") {
        borderColor = "#ffb000";
        accentColor = "#ffb000";
        badgeBg = "#261900";
        cardBg = "#120c02";
      }

      if (isSelected) {
        borderColor = "#ffffff";
      }

      calculatedNodes.push({
        id: span.span_id,
        position: { x: posX, y: posY },
        data: {
          label: (
            <div
              onClick={() => onSelectSpan(span)}
              style={{
                background: cardBg,
                border: `1px solid ${borderColor}`,
                boxShadow: isSelected
                  ? "0 0 0 1px #ffffff, 0 8px 24px rgba(0,255,102,0.18)"
                  : isLoop
                  ? "0 0 14px rgba(255,51,51,0.3)"
                  : "0 4px 14px rgba(0,0,0,0.8)",
                width: 210,
              }}
              className="p-3 font-mono text-left cursor-pointer transition-all"
            >
              <div className="flex items-center justify-between gap-1.5 mb-1.5">
                <span
                  style={{ background: badgeBg, color: accentColor, borderColor }}
                  className="px-1.5 py-0.5 text-[9px] font-bold border uppercase tracking-wider"
                >
                  #{index + 1} • {span.span_kind}
                </span>
                {isLoop ? (
                  <span className="px-1.5 py-0.5 text-[9px] bg-[#ff3333] text-black font-extrabold tracking-wider">
                    LOOP TRIP
                  </span>
                ) : (
                  <span className="text-[10px] text-[#737373]">
                    {span.latency_ms.toFixed(0)}ms
                  </span>
                )}
              </div>

              <div
                style={{ color: accentColor }}
                className="text-xs font-bold truncate mb-1.5"
                title={displayLabel}
              >
                {displayLabel}
              </div>

              <div className="flex items-center justify-between text-[10px] text-[#888888] pt-1.5 border-t border-[#1f1f1f]">
                <span>
                  {span.prompt_tokens + span.completion_tokens > 0
                    ? `${span.prompt_tokens + span.completion_tokens} tok`
                    : span.operation_name}
                </span>
                <span className="text-white font-semibold">
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
          label: isLoop ? "REPEAT" : undefined,
          labelStyle: { fill: "#ff5555", fontWeight: 700, fontSize: 9 },
          labelBgStyle: { fill: "#1a0000", fillOpacity: 0.9 },
          style: {
            stroke: isLoop ? "#ff3333" : "#00ff66",
            strokeWidth: isLoop ? 2.2 : 1.5,
          },
          markerEnd: {
            type: MarkerType.ArrowClosed,
            color: isLoop ? "#ff3333" : "#00ff66",
          },
        });
      }
    });

    // Add cyclic feedback edge if loop detected across multiple spans
    if (firstLoopSpanId && lastLoopSpanId && firstLoopSpanId !== lastLoopSpanId) {
      calculatedEdges.push({
        id: `cycle-${lastLoopSpanId}-${firstLoopSpanId}`,
        source: lastLoopSpanId,
        target: firstLoopSpanId,
        animated: true,
        label: "3-TIER CIRCUIT BREAKER TRIP",
        labelStyle: { fill: "#ff3333", fontWeight: 800, fontSize: 9 },
        labelBgStyle: { fill: "#000000", fillOpacity: 0.95 },
        style: {
          stroke: "#ff3333",
          strokeWidth: 2,
          strokeDasharray: "5 5",
        },
        markerEnd: {
          type: MarkerType.ArrowClosed,
          color: "#ff3333",
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
    <div className="terminal-card flex flex-col">
      {/* Header with Mode Switcher */}
      <div className="dot-matrix-header flex flex-wrap items-center justify-between gap-3 px-4 py-3 text-xs">
        <div className="flex items-center gap-2.5">
          <GitBranch className="h-4 w-4 text-[#00ff66]" />
          <span className="text-[#00ff66]">
            [ 02 // LANGGRAPH TOPOLOGY & DOTTED-ORDER TRACE WATERFALL ]
          </span>
          {loopDetectedCount >= 3 && (
            <span className="inline-flex items-center gap-1 border border-[#ff3333] bg-[#240303] px-2 py-0.5 text-[10px] font-bold text-[#ff3333] pulse-red">
              <AlertOctagon className="h-3 w-3" />
              RECURSIVE CYCLE DETECTED ({loopDetectedCount}x)
            </span>
          )}
        </div>

        <div className="flex items-center gap-2">
          <span className="text-[11px] text-[#737373] mr-1">
            {spans.length} SPANS
          </span>
          <button
            onClick={() => setDisplayMode("DAG")}
            className={`flex items-center gap-1.5 px-2.5 py-1 text-[10px] font-bold border cursor-pointer transition-colors ${
              displayMode === "DAG"
                ? "border-[#00ff66] bg-[#00ff66] text-black"
                : "border-[#262626] bg-[#0a0a0a] text-[#888888] hover:text-white"
            }`}
          >
            <GitBranch className="h-3 w-3" />
            <span>CYCLIC DAG</span>
          </button>
          <button
            onClick={() => setDisplayMode("WATERFALL")}
            className={`flex items-center gap-1.5 px-2.5 py-1 text-[10px] font-bold border cursor-pointer transition-colors ${
              displayMode === "WATERFALL"
                ? "border-[#00ff66] bg-[#00ff66] text-black"
                : "border-[#262626] bg-[#0a0a0a] text-[#888888] hover:text-white"
            }`}
          >
            <ListTree className="h-3 w-3" />
            <span>TRACE WATERFALL</span>
          </button>
        </div>
      </div>

      {/* Main Visualization Viewport */}
      {spans.length === 0 ? (
        <div className="flex h-[320px] items-center justify-center text-xs text-[#666666] font-mono bg-[#030303]">
          SELECT AN AGENT SESSION OR CLICK [SEED DEMO SCENARIO] TO RENDER EXECUTION TOPOLOGY
        </div>
      ) : displayMode === "DAG" ? (
        <div className="relative h-[340px] w-full bg-[#020202]">
          <div className="absolute inset-0">
            <ReactFlow
              key={flowKey}
              nodes={nodes}
              edges={edges}
              fitView
              fitViewOptions={{ padding: 0.22 }}
              minZoom={0.4}
              maxZoom={1.6}
              attributionPosition="bottom-right"
            >
              <Background
                variant={BackgroundVariant.Dots}
                gap={20}
                size={1.2}
                color="rgba(255, 255, 255, 0.12)"
              />
              <Controls />
            </ReactFlow>
          </div>
        </div>
      ) : (
        <div className="h-[340px] overflow-y-auto p-3.5 space-y-2 bg-[#030303] font-mono">
          {spans.map((span, idx) => {
            const isSelected = selectedSpan?.span_id === span.span_id;
            const depth = Math.max(0, (span.dotted_order.match(/\./g) || []).length);
            const widthPct = Math.max(6, (span.latency_ms / maxLatency) * 100);
            const toolName = span.attributes?.tool_name as string | undefined;

            return (
              <div
                key={span.span_id}
                onClick={() => onSelectSpan(span)}
                style={{ marginLeft: `${Math.min(depth * 18, 72)}px` }}
                className={`border p-2.5 cursor-pointer transition-all ${
                  isSelected
                    ? "border-white bg-[#121212]"
                    : "border-[#1f1f1f] bg-[#070707] hover:border-[#383838]"
                }`}
              >
                <div className="flex items-center justify-between gap-2 text-xs mb-1.5">
                  <div className="flex items-center gap-2">
                    <span className="text-[10px] text-[#666666]">#{idx + 1}</span>
                    <span className="border border-[#2e2e2e] bg-[#111111] px-1.5 py-0.5 text-[10px] font-bold text-[#00ff66]">
                      {span.span_kind}
                    </span>
                    <span className="font-bold text-white">
                      {toolName ? `${span.name} (${toolName})` : span.name}
                    </span>
                    {span.redacted && (
                      <span className="inline-flex items-center gap-1 border border-[#ffb000] bg-[#1f1300] px-1.5 py-0.5 text-[9px] text-[#ffb000]">
                        <Shield className="h-2.5 w-2.5" />
                        PII REDACTED
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-3 text-[11px]">
                    <span className="text-[#a3a3a3]">{span.latency_ms.toFixed(1)} ms</span>
                    <span className="text-[#00ff66] font-bold">${span.cost_usd.toFixed(5)}</span>
                  </div>
                </div>
                <div className="h-1.5 w-full bg-[#141414] overflow-hidden">
                  <div
                    className="h-full bg-[#00e5ff]"
                    style={{ width: `${widthPct}%` }}
                  />
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Selected Span & OpenInference Inspector */}
      {selectedSpan && (
        <div className="border-t border-[#262626] bg-[#060606] p-4 font-mono text-xs">
          <div className="flex flex-wrap items-center justify-between gap-2 pb-3 mb-3 border-b border-[#1a1a1a]">
            <div className="flex items-center gap-2.5">
              <Code2 className="h-4 w-4 text-[#00e5ff]" />
              <span className="font-bold text-white text-sm">
                SPAN TELEMETRY // {selectedSpan.name}
              </span>
              <span className="border border-[#2e2e2e] bg-[#111111] px-2 py-0.5 text-[10px] text-[#00e5ff]">
                {selectedSpan.span_kind} • {selectedSpan.operation_name}
              </span>
            </div>

            <div className="flex items-center gap-2">
              <button
                onClick={() => setInspectorTab("PAYLOADS")}
                className={`px-2.5 py-1 text-[10px] font-bold border cursor-pointer ${
                  inspectorTab === "PAYLOADS"
                    ? "border-[#00e5ff] bg-[#00e5ff] text-black"
                    : "border-[#262626] text-[#888888] hover:text-white"
                }`}
              >
                INPUT / OUTPUT PAYLOADS
              </button>
              <button
                onClick={() => setInspectorTab("ATTRIBUTES")}
                className={`px-2.5 py-1 text-[10px] font-bold border cursor-pointer ${
                  inspectorTab === "ATTRIBUTES"
                    ? "border-[#00e5ff] bg-[#00e5ff] text-black"
                    : "border-[#262626] text-[#888888] hover:text-white"
                }`}
              >
                OTEL & DOTTED_ORDER METADATA
              </button>
            </div>
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5 mb-3 text-[11px]">
            <div className="border border-[#1c1c1c] bg-[#0a0a0a] p-2.5">
              <div className="text-[#737373] flex items-center gap-1 mb-0.5">
                <Coins className="h-3 w-3 text-[#00ff66]" /> SPAN COST
              </div>
              <div className="text-[#00ff66] font-bold text-sm">
                ${selectedSpan.cost_usd.toFixed(5)}
              </div>
            </div>
            <div className="border border-[#1c1c1c] bg-[#0a0a0a] p-2.5">
              <div className="text-[#737373] flex items-center gap-1 mb-0.5">
                <Clock className="h-3 w-3 text-[#00e5ff]" /> LATENCY
              </div>
              <div className="text-white font-bold text-sm">
                {selectedSpan.latency_ms.toFixed(1)} ms
              </div>
            </div>
            <div className="border border-[#1c1c1c] bg-[#0a0a0a] p-2.5">
              <div className="text-[#737373] flex items-center gap-1 mb-0.5">
                <Cpu className="h-3 w-3 text-[#ffb000]" /> PROMPT TOKENS
              </div>
              <div className="text-white font-bold text-sm">
                {selectedSpan.prompt_tokens}
              </div>
            </div>
            <div className="border border-[#1c1c1c] bg-[#0a0a0a] p-2.5">
              <div className="text-[#737373] flex items-center gap-1 mb-0.5">
                <Cpu className="h-3 w-3 text-[#00ff66]" /> COMPLETION TOKENS
              </div>
              <div className="text-white font-bold text-sm">
                {selectedSpan.completion_tokens}
              </div>
            </div>
          </div>

          {inspectorTab === "PAYLOADS" ? (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-[11px]">
              <div className="border border-[#1f1f1f] bg-[#030303] p-2.5">
                <div className="text-[10px] font-bold text-[#737373] mb-1">
                  INPUT PAYLOAD (PII SCRUBBED AT EDGE):
                </div>
                <pre className="text-[#d4d4d4] overflow-x-auto max-h-24">
                  {JSON.stringify(selectedSpan.input_payload, null, 2)}
                </pre>
              </div>
              <div className="border border-[#1f1f1f] bg-[#030303] p-2.5">
                <div className="text-[10px] font-bold text-[#737373] mb-1">
                  OUTPUT PAYLOAD / THOUGHT TRACE:
                </div>
                <pre className="text-[#00ff66] overflow-x-auto max-h-24">
                  {JSON.stringify(selectedSpan.output_payload, null, 2)}
                </pre>
              </div>
            </div>
          ) : (
            <div className="border border-[#1f1f1f] bg-[#030303] p-2.5 text-[11px] space-y-1.5">
              <div className="flex justify-between border-b border-[#171717] pb-1">
                <span className="text-[#737373]">SPAN_ID (UUIDv7):</span>
                <span className="text-white">{selectedSpan.span_id}</span>
              </div>
              <div className="flex justify-between border-b border-[#171717] pb-1">
                <span className="text-[#737373]">DOTTED_ORDER HIERARCHY:</span>
                <span className="text-[#00e5ff] truncate max-w-[360px]" title={selectedSpan.dotted_order}>
                  {selectedSpan.dotted_order}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-[#737373]">ATTRIBUTES:</span>
                <span className="text-[#a3a3a3]">
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
