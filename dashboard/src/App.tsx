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
  CheckpointRecord,
  AuditLogResponse,
  WorkflowROIAttribution,
  ModelBenchmarkEntry,
  DowngradeRecommendation,
  ContainerLog,
} from "./types";

export const App: React.FC = () => {
  const [wsConnected, setWsConnected] = useState<boolean>(false);
  const [seeding, setSeeding] = useState<boolean>(false);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [sessions, setSessions] = useState<AgentSession[]>([]);
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null);
  const [spans, setSpans] = useState<ArgusSpan[]>([]);
  const [selectedSpan, setSelectedSpan] = useState<ArgusSpan | null>(null);
  const [pendingTools, setPendingTools] = useState<PendingToolCall[]>([]);
  const [latestCheckpoint, setLatestCheckpoint] = useState<CheckpointRecord | null>(null);
  const [auditLog, setAuditLog] = useState<AuditLogResponse | null>(null);
  const [roi, setRoi] = useState<WorkflowROIAttribution | null>(null);
  const [benchmarks, setBenchmarks] = useState<ModelBenchmarkEntry[]>([]);
  const [recommendations, setRecommendations] = useState<DowngradeRecommendation[]>([]);
  const [logs, setLogs] = useState<ContainerLog[]>([]);

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

  const fetchCloudWatchLogs = useCallback(async () => {
    try {
      const res = await fetch("/api/v1/telemetry/cloudwatch");
      if (res.ok) {
        const data: ContainerLog[] = await res.json();
        setLogs(data);
      }
    } catch {
      // Offline fallback
    }
  }, []);

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

  const fetchSessionDetails = useCallback(async (sessionId: string) => {
    try {
      const [spansRes, toolsRes, cpRes, auditRes, roiRes] = await Promise.all([
        fetch(`/api/v1/telemetry/sessions/${sessionId}/spans`),
        fetch(`/api/v1/c2/${sessionId}/pending-tools`),
        fetch(`/api/v1/c2/${sessionId}/checkpoints/latest`),
        fetch(`/api/v1/c2/${sessionId}/audit-log`),
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
      if (cpRes.ok) {
        const cpData: CheckpointRecord | null = await cpRes.json();
        setLatestCheckpoint(cpData);
      }
      if (auditRes.ok) {
        const auditData: AuditLogResponse = await auditRes.json();
        setAuditLog(auditData);
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
    fetchCloudWatchLogs();
  }, [fetchSessions, fetchBenchmarks, fetchCloudWatchLogs]);

  useEffect(() => {
    if (selectedSessionId) {
      fetchSessionDetails(selectedSessionId);
    }
  }, [selectedSessionId, fetchSessionDetails]);

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
            if (
              data.channel === "telemetry.spans" ||
              data.channel === "telemetry.sessions" ||
              data.channel === "governance.circuit_breaker" ||
              data.channel === "c2.state_changed" ||
              data.channel === "c2.checkpoint_created" ||
              data.channel === "c2.intervention_required" ||
              data.channel === "c2.override_resolved"
            ) {
              fetchSessions();
              if (selectedSessionId) fetchSessionDetails(selectedSessionId);
            } else if (data.channel === "telemetry.cloudwatch") {
              fetchCloudWatchLogs();
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
  }, [fetchSessions, fetchSessionDetails, fetchCloudWatchLogs, selectedSessionId]);

  const handleSeedScenario = async () => {
    setSeeding(true);
    setStatusMessage("Seeding multi-agent scenario...");
    try {
      const res = await fetch("/api/v1/demo/seed", { method: "POST" });
      if (res.ok) {
        const data = await res.json();
        await fetchSessions();
        await fetchCloudWatchLogs();
        if (data.paused_c2_session_id) {
          setSelectedSessionId(data.paused_c2_session_id);
          await fetchSessionDetails(data.paused_c2_session_id);
        }
        setStatusMessage("Seeded 3 live agent sessions (LangGraph Loop, CrewAI Paused C2, AutoGPT FinOps).");
      }
    } finally {
      setSeeding(false);
    }
  };

  const handlePause = async (sessionId: string) => {
    const res = await fetch(`/api/v1/c2/${sessionId}/pause`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ operator_id: "human_op", reason: "Operator manual pause" }),
    });
    if (res.ok) {
      setStatusMessage(`Session ${sessionId.substring(0, 8)} transitioned to PAUSED_C2.`);
      fetchSessions();
      if (selectedSessionId === sessionId) fetchSessionDetails(sessionId);
    }
  };

  const handleResume = async (sessionId: string) => {
    const res = await fetch(`/api/v1/c2/${sessionId}/resume`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ operator_id: "human_op", reason: "Operator resumed session" }),
    });
    if (res.ok) {
      setStatusMessage(`Session ${sessionId.substring(0, 8)} resumed (loop tracker cleared).`);
      fetchSessions();
      if (selectedSessionId === sessionId) fetchSessionDetails(sessionId);
    }
  };

  const handleTerminate = async (sessionId: string) => {
    const res = await fetch(`/api/v1/c2/${sessionId}/terminate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ operator_id: "human_op", reason: "Operator kill switch" }),
    });
    if (res.ok) {
      setStatusMessage(`Session ${sessionId.substring(0, 8)} terminated.`);
      fetchSessions();
      if (selectedSessionId === sessionId) fetchSessionDetails(sessionId);
    }
  };

  const handleApproveTool = async (toolCallId: string) => {
    if (!selectedSessionId) return;
    const res = await fetch(`/api/v1/c2/${selectedSessionId}/tool-override`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        tool_call_id: toolCallId,
        decision: "approve",
        operator_id: "human_op",
        reason: "Security inspection cleared",
      }),
    });
    if (res.ok) {
      setStatusMessage(`Tool call ${toolCallId} approved and logged to SHA-256 chain.`);
      fetchSessionDetails(selectedSessionId);
    }
  };

  const handleEditTool = async (
    toolCallId: string,
    modifiedArgs: Record<string, unknown>
  ) => {
    if (!selectedSessionId) return;
    const res = await fetch(`/api/v1/c2/${selectedSessionId}/tool-override`, {
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
    if (res.ok) {
      setStatusMessage(`Tool call ${toolCallId} arguments modified and authorized.`);
      fetchSessionDetails(selectedSessionId);
    }
  };

  const handleMockTool = async (
    toolCallId: string,
    mockOutput: Record<string, unknown>
  ) => {
    if (!selectedSessionId) return;
    const res = await fetch(`/api/v1/c2/${selectedSessionId}/tool-override`, {
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
    if (res.ok) {
      setStatusMessage(`Tool call ${toolCallId} bypassed with operator mock response.`);
      fetchSessionDetails(selectedSessionId);
    }
  };

  const handleRejectTool = async (toolCallId: string, reason: string) => {
    if (!selectedSessionId) return;
    const res = await fetch(`/api/v1/c2/${selectedSessionId}/tool-override`, {
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
    if (res.ok) {
      setStatusMessage(`Tool call ${toolCallId} rejected by operator.`);
      fetchSessionDetails(selectedSessionId);
    }
  };

  const handleApplyPatch = async (patchesJson: string) => {
    if (!selectedSessionId) return;
    try {
      const patches = JSON.parse(patchesJson);
      const expectedCpId =
        latestCheckpoint?.checkpoint_id ??
        sessions.find((s) => s.session_id === selectedSessionId)?.latest_checkpoint_id ??
        null;

      const res = await fetch(`/api/v1/c2/${selectedSessionId}/patch`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          operator_id: "human_op",
          expected_parent_checkpoint_id: expectedCpId,
          patches: patches,
          reason: "Manual RFC 6902 memory mutation",
        }),
      });
      if (res.ok) {
        const newCp: CheckpointRecord = await res.json();
        setStatusMessage(
          `RFC 6902 Patch Applied! New Checkpoint: ${newCp.checkpoint_id.substring(0, 8)}`
        );
        fetchSessions();
        fetchSessionDetails(selectedSessionId);
      } else {
        const err = await res.json();
        setStatusMessage(`Patch Rejected: ${err.detail || JSON.stringify(err)}`);
      }
    } catch {
      setStatusMessage("Invalid JSON Patch syntax.");
    }
  };

  return (
    <div className="flex flex-col min-h-screen bg-black text-[#e0e0e0] font-mono">
      <Header
        wsConnected={wsConnected}
        sessions={sessions}
        pendingInterventionsCount={pendingTools.length}
        onSeedScenario={handleSeedScenario}
        seeding={seeding}
      />

      <main className="flex-1 p-4 grid grid-cols-1 lg:grid-cols-12 gap-4">
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

        <div className="lg:col-span-7 flex flex-col space-y-4">
          <LangGraphVisualizer
            spans={spans}
            selectedSpan={selectedSpan}
            onSelectSpan={(span) => setSelectedSpan(span)}
          />

          <C2ControlPanel
            sessionId={selectedSessionId}
            pendingTools={pendingTools}
            latestCheckpoint={latestCheckpoint}
            auditLog={auditLog}
            statusMessage={statusMessage}
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

      <footer className="border-t border-[#181818] bg-[#000000] px-6 py-2 flex justify-between text-[10px] text-[#555555]">
        <div>ARGUS AGENT GOVERNANCE CONTROL PLANE // LOCAL ZERO-SPEND STACK</div>
        <div>OPENTELEMETRY • LANGGRAPH • CREWAI • PHOENIX OSS • RFC 6902</div>
      </footer>
    </div>
  );
};
