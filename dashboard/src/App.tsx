import React, { useState, useEffect, useCallback } from "react";
import { Header } from "./components/Header";
import { FleetOverview } from "./components/FleetOverview";
import { LangGraphVisualizer } from "./components/LangGraphVisualizer";
import { C2ControlPanel } from "./components/C2ControlPanel";
import { RoiAndBenchmarks } from "./components/RoiAndBenchmarks";
import { LogWaterfall } from "./components/LogWaterfall";
import {
  AgentSession,
  ArgusSpan,
  PendingToolCall,
  WorkflowROIAttribution,
  ModelBenchmarkEntry,
  DowngradeRecommendation,
  ContainerLog,
} from "./types";

export const App: React.FC = () => {
  const [wsConnected, setWsConnected] = useState<boolean>(false);
  const [sessions, setSessions] = useState<AgentSession[]>([]);
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null);
  const [spans, setSpans] = useState<ArgusSpan[]>([]);
  const [selectedSpan, setSelectedSpan] = useState<ArgusSpan | null>(null);
  const [pendingTools, setPendingTools] = useState<PendingToolCall[]>([]);
  const [roi, setRoi] = useState<WorkflowROIAttribution | null>(null);
  const [benchmarks, setBenchmarks] = useState<ModelBenchmarkEntry[]>([]);
  const [recommendations, setRecommendations] = useState<DowngradeRecommendation[]>([]);
  const [logs, setLogs] = useState<ContainerLog[]>([]);

  // 1. Fetch initial sessions and benchmark catalog
  const fetchSessions = useCallback(async () => {
    try {
      const res = await fetch("/api/v1/telemetry/sessions");
      if (res.ok) {
        const data: AgentSession[] = await res.json();
        setSessions(data);
        if (data.length > 0 && !selectedSessionId) {
          setSelectedSessionId(data[0].session_id);
        }
      }
    } catch {
      // Offline fallback
    }
  }, [selectedSessionId]);

  const fetchBenchmarks = useCallback(async () => {
    try {
      const res = await fetch("/api/v1/attribution/benchmarks/catalog");
      if (res.ok) {
        const data = await res.json();
        setBenchmarks(data);
      }
      const recRes = await fetch("/api/v1/attribution/benchmarks/recommend", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ current_model: "claude-3-5-sonnet", min_acceptable_accuracy: 0.5 }),
      });
      if (recRes.ok) {
        const recData = await recRes.json();
        setRecommendations(recData);
      }
    } catch {
      // Offline fallback
    }
  }, []);

  // 2. Fetch session specific telemetry
  const fetchSessionDetails = useCallback(async (sessionId: string) => {
    try {
      const [spansRes, toolsRes, roiRes] = await Promise.all([
        fetch(`/api/v1/telemetry/sessions/${sessionId}/spans`),
        fetch(`/api/v1/c2/${sessionId}/pending-tools`),
        fetch(`/api/v1/attribution/roi/${sessionId}?assigned_business_value_usd=100.0`),
      ]);

      if (spansRes.ok) {
        const sData: ArgusSpan[] = await spansRes.json();
        setSpans(sData);
        if (sData.length > 0) setSelectedSpan(sData[sData.length - 1]);
      }
      if (toolsRes.ok) {
        const tData: PendingToolCall[] = await toolsRes.json();
        setPendingTools(tData);
      }
      if (roiRes.ok) {
        const rData: WorkflowROIAttribution = await roiRes.json();
        setRoi(rData);
      }
    } catch {
      // Offline fallback
    }
  }, []);

  useEffect(() => {
    fetchSessions();
    fetchBenchmarks();
  }, [fetchSessions, fetchBenchmarks]);

  useEffect(() => {
    if (selectedSessionId) {
      fetchSessionDetails(selectedSessionId);
    }
  }, [selectedSessionId, fetchSessionDetails]);

  // 3. WebSocket Real-time event subscription
  useEffect(() => {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const host = window.location.host;
    const wsUrl = `${protocol}//${host}/ws/v1/stream?tenant_id=default_tenant&workspace_id=default_workspace`;

    let ws: WebSocket | null = null;
    let reconnectTimer: number | null = null;

    const connect = () => {
      try {
        ws = new WebSocket(wsUrl);

        ws.onopen = () => {
          setWsConnected(true);
        };

        ws.onmessage = (event) => {
          try {
            const data = JSON.parse(event.data);
            if (data.channel === "telemetry.spans" || data.topic === "span.ingested") {
              fetchSessions();
              if (selectedSessionId) fetchSessionDetails(selectedSessionId);
            } else if (
              data.channel === "governance.circuit_breaker" ||
              data.topic === "circuit_breaker.tripped"
            ) {
              fetchSessions();
            } else if (
              data.channel === "c2.intervention_required" ||
              data.channel === "c2.override_resolved"
            ) {
              if (selectedSessionId) fetchSessionDetails(selectedSessionId);
            } else if (data.channel === "telemetry.cloudwatch") {
              setLogs((prev) => [
                {
                  log_id: String(Date.now()),
                  timestamp: new Date().toISOString(),
                  log_group: "/aws/ecs/ai-workers",
                  log_stream: "worker-0",
                  severity: data.event?.anomalies_count > 0 ? "ERROR" : "INFO",
                  message: `CloudWatch batch ingested: ${data.event?.total_logs ?? 0} events.`,
                  is_container_anomaly: (data.event?.anomalies_count ?? 0) > 0,
                  trace_id: null,
                  span_id: null,
                },
                ...prev.slice(0, 49),
              ]);
            }
          } catch {
            // Non-JSON frame
          }
        };

        ws.onclose = () => {
          setWsConnected(false);
          reconnectTimer = window.setTimeout(connect, 3000);
        };

        ws.onerror = () => {
          setWsConnected(false);
          ws?.close();
        };
      } catch {
        setWsConnected(false);
        reconnectTimer = window.setTimeout(connect, 3000);
      }
    };

    connect();

    return () => {
      if (reconnectTimer) clearTimeout(reconnectTimer);
      ws?.close();
    };
  }, [fetchSessions, fetchSessionDetails, selectedSessionId]);

  // 4. Operator C2 Handlers
  const handlePause = async (sessionId: string) => {
    await fetch(`/api/v1/c2/${sessionId}/pause`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ operator_id: "human_op", reason: "Operator manual pause" }),
    });
    fetchSessions();
  };

  const handleResume = async (sessionId: string) => {
    await fetch(`/api/v1/c2/${sessionId}/resume`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ operator_id: "human_op", reason: "Operator resumed session" }),
    });
    fetchSessions();
  };

  const handleTerminate = async (sessionId: string) => {
    await fetch(`/api/v1/c2/${sessionId}/terminate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ operator_id: "human_op", reason: "Operator kill switch" }),
    });
    fetchSessions();
  };

  const handleApproveTool = async (toolCallId: string) => {
    if (!selectedSessionId) return;
    await fetch(`/api/v1/c2/${selectedSessionId}/tool-override`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        tool_call_id: toolCallId,
        decision: "approve",
        operator_id: "human_op",
        reason: "Security inspection cleared",
      }),
    });
    fetchSessionDetails(selectedSessionId);
  };

  const handleEditTool = async (
    toolCallId: string,
    modifiedArgs: Record<string, unknown>
  ) => {
    if (!selectedSessionId) return;
    await fetch(`/api/v1/c2/${selectedSessionId}/tool-override`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        tool_call_id: toolCallId,
        decision: "edit",
        modified_args: modifiedArgs,
        operator_id: "human_op",
        reason: "Parameters sanitized for sandbox execution",
      }),
    });
    fetchSessionDetails(selectedSessionId);
  };

  const handleMockTool = async (
    toolCallId: string,
    mockOutput: Record<string, unknown>
  ) => {
    if (!selectedSessionId) return;
    await fetch(`/api/v1/c2/${selectedSessionId}/tool-override`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        tool_call_id: toolCallId,
        decision: "mock",
        mock_output: mockOutput,
        operator_id: "human_op",
        reason: "Injected deterministic mock fixture",
      }),
    });
    fetchSessionDetails(selectedSessionId);
  };

  const handleRejectTool = async (toolCallId: string, reason: string) => {
    if (!selectedSessionId) return;
    await fetch(`/api/v1/c2/${selectedSessionId}/tool-override`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        tool_call_id: toolCallId,
        decision: "reject",
        rejection_reason: reason,
        operator_id: "human_op",
        reason: "Violated organizational safety guardrail",
      }),
    });
    fetchSessionDetails(selectedSessionId);
  };

  const handleApplyPatch = async (patchesJson: string) => {
    if (!selectedSessionId) return;
    try {
      const patches = JSON.parse(patchesJson);
      const res = await fetch(`/api/v1/c2/${selectedSessionId}/patch`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          operator_id: "human_op",
          expected_parent_checkpoint_id:
            sessions.find((s) => s.session_id === selectedSessionId)?.latest_checkpoint_id ||
            "00000000-0000-0000-0000-000000000000",
          patches: patches,
          reason: "Manual state update",
        }),
      });
      if (res.ok) {
        alert("RFC 6902 Patch Applied Successfully!");
        fetchSessionDetails(selectedSessionId);
      } else {
        const err = await res.json();
        alert(`Patch Failed: ${err.detail || JSON.stringify(err)}`);
      }
    } catch {
      alert("Invalid JSON Patch syntax");
    }
  };

  return (
    <div className="flex flex-col min-h-screen bg-black text-[#e0e0e0] font-mono">
      {/* 1. Header Bar */}
      <Header
        wsConnected={wsConnected}
        sessions={sessions}
        pendingInterventionsCount={pendingTools.length}
      />

      {/* Main Grid View */}
      <main className="flex-1 p-4 grid grid-cols-1 lg:grid-cols-12 gap-4">
        {/* Left Column (5 Cols): Fleet State Matrix & Log Stream */}
        <div className="lg:col-span-5 flex flex-col space-y-4">
          <FleetOverview
            sessions={sessions}
            selectedSessionId={selectedSessionId}
            onSelectSession={(id) => setSelectedSessionId(id)}
            onPause={handlePause}
            onResume={handleResume}
            onTerminate={handleTerminate}
          />
          <LogWaterfall logs={logs} />
        </div>

        {/* Right Column (7 Cols): Topology Visualizer, C2 Controls, ROI */}
        <div className="lg:col-span-7 flex flex-col space-y-4">
          <LangGraphVisualizer
            spans={spans}
            selectedSpan={selectedSpan}
            onSelectSpan={(span) => setSelectedSpan(span)}
          />

          <C2ControlPanel
            sessionId={selectedSessionId}
            pendingTools={pendingTools}
            onApproveTool={handleApproveTool}
            onEditTool={handleEditTool}
            onMockTool={handleMockTool}
            onRejectTool={handleRejectTool}
            onApplyPatch={handleApplyPatch}
          />

          <RoiAndBenchmarks
            roi={roi}
            benchmarks={benchmarks}
            recommendations={recommendations}
          />
        </div>
      </main>

      {/* Footer Info Strip */}
      <footer className="border-t border-[#181818] bg-[#000000] px-6 py-2 flex justify-between text-[10px] text-[#555555]">
        <div>ARGUS AGENT GOVERNANCE CONTROL PLANE // LOCAL ZERO-SPEND STACK</div>
        <div>OPENTELEMETRY • LANGGRAPH • CREWAI • PHOENIX OSS • RFC 6902</div>
      </footer>
    </div>
  );
};
