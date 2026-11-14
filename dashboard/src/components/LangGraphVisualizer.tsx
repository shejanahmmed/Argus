import React, { useMemo } from "react";
import {
  ReactFlow,
  Controls,
  Background,
  BackgroundVariant,
  Node,
  Edge,
  MarkerType,
} from "@xyflow/react";
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
  const { nodes, edges } = useMemo(() => {
    if (spans.length === 0) {
      return { nodes: [], edges: [] };
    }

    const calculatedNodes: Node[] = [];
    const calculatedEdges: Edge[] = [];
    const xSpacing = 220;
    const ySpacing = 110;

    // Detect loops: check if multiple spans have identical name or tool_name
    const nameCount: Record<string, number> = {};
    spans.forEach((s) => {
      const key = (s.attributes?.tool_name as string) || s.name;
      nameCount[key] = (nameCount[key] || 0) + 1;
    });

    spans.forEach((span, index) => {
      const toolName = span.attributes?.tool_name as string | undefined;
      const label = toolName ? `TOOL: ${toolName}` : span.name;
      const isLoop = (nameCount[label] || 0) >= 3;
      const isSelected = selectedSpan?.span_id === span.span_id;

      // Arrange nodes in snake / zig-zag graph
      const col = index % 4;
      const row = Math.floor(index / 4);
      const posX = 40 + col * xSpacing;
      const posY = 40 + row * ySpacing;

      let borderStyle = "#222222";
      let textStyle = "#cccccc";
      let bgStyle = "#080808";

      if (isLoop) {
        borderStyle = "#ff3333";
        textStyle = "#ff6666";
        bgStyle = "#200505";
      } else if (span.span_kind === "TOOL") {
        borderStyle = "#00e5ff";
        textStyle = "#00e5ff";
        bgStyle = "#001518";
      } else if (span.span_kind === "LLM") {
        borderStyle = "#00ff66";
        textStyle = "#00ff66";
        bgStyle = "#001408";
      }

      if (isSelected) {
        borderStyle = "#ffffff";
        bgStyle = "#181818";
      }

      calculatedNodes.push({
        id: span.span_id,
        position: { x: posX, y: posY },
        data: {
          label: (
            <div
              className="p-2.5 font-mono text-[11px] text-left cursor-pointer"
              style={{ color: textStyle }}
              onClick={() => onSelectSpan(span)}
            >
              <div className="flex items-center justify-between mb-1">
                <span className="font-bold truncate max-w-[130px]">{label}</span>
                {isLoop && (
                  <span className="text-[9px] px-1 bg-[#ff3333] text-black font-bold">
                    LOOP!
                  </span>
                )}
              </div>
              <div className="text-[10px] text-[#888888]">
                {span.span_kind} • {span.cost_usd > 0 ? `$${span.cost_usd.toFixed(4)}` : `${span.latency_ms.toFixed(0)}ms`}
              </div>
            </div>
          ),
        },
        style: {
          background: bgStyle,
          border: `1px solid ${borderStyle}`,
          width: 180,
          borderRadius: 0,
        },
      });

      // Connect sequentially or via parent_span_id
      if (index > 0) {
        const prevSpan = spans[index - 1];
        const isLoopEdge = isLoop;
        calculatedEdges.push({
          id: `e-${prevSpan.span_id}-${span.span_id}`,
          source: prevSpan.span_id,
          target: span.span_id,
          animated: isLoopEdge,
          style: {
            stroke: isLoopEdge ? "#ff3333" : "#333333",
            strokeWidth: isLoopEdge ? 2 : 1,
          },
          markerEnd: {
            type: MarkerType.ArrowClosed,
            color: isLoopEdge ? "#ff3333" : "#444444",
          },
        });
      }
    });

    return { nodes: calculatedNodes, edges: calculatedEdges };
  }, [spans, selectedSpan, onSelectSpan]);

  return (
    <div className="terminal-card flex flex-col h-full min-h-[380px]">
      <div className="dot-matrix-header flex items-center justify-between px-4 py-2 text-xs">
        <span className="text-[#00ff66]">[ 02 // LANGGRAPH TOPOLOGY & RECURSIVE LOOP TRACE ]</span>
        <span className="text-[#666666]">
          {spans.length > 0 ? `${spans.length} EXECUTION SPANS` : "SELECT A SESSION"}
        </span>
      </div>

      <div className="flex-1 w-full h-full min-h-[320px] bg-black">
        {spans.length === 0 ? (
          <div className="flex h-full items-center justify-center text-xs text-[#555555] font-mono">
            SELECT A SESSION FROM THE FLEET MATRIX TO RENDER TOPOLOGY
          </div>
        ) : (
          <ReactFlow
            nodes={nodes}
            edges={edges}
            fitView
            attributionPosition="bottom-right"
          >
            <Background
              variant={BackgroundVariant.Dots}
              gap={16}
              size={1}
              color="rgba(255, 255, 255, 0.08)"
            />
            <Controls />
          </ReactFlow>
        )}
      </div>

      {selectedSpan && (
        <div className="border-t border-[#222222] bg-[#050505] p-3 text-xs font-mono">
          <div className="flex items-center justify-between text-[#888888] mb-1">
            <span className="text-white font-bold">SPAN INSPECTION: {selectedSpan.name}</span>
            <span>ID: {selectedSpan.span_id}</span>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-[11px] text-[#aaaaaa]">
            <div>KIND: <span className="text-white">{selectedSpan.span_kind}</span></div>
            <div>COST: <span className="text-[#00ff66]">${selectedSpan.cost_usd.toFixed(5)}</span></div>
            <div>PROMPT TOKENS: <span className="text-white">{selectedSpan.prompt_tokens}</span></div>
            <div>COMPLETION TOKENS: <span className="text-white">{selectedSpan.completion_tokens}</span></div>
          </div>
        </div>
      )}
    </div>
  );
};
