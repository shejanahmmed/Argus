import React, { useState, useEffect, useCallback } from "react";
import { X } from "lucide-react";
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
  ViewMode,
  WorkerLease,
  ReapLeasesResponse,
  StorageDiagnostics,
  ReadyzResponse,
} from "./types";

export const App: React.FC = () => {
  const [wsConnected, setWsConnected] = useState<boolean>(false);
  const [seeding, setSeeding] = useState<boolean>(false);
  const [activeView, setActiveView] = useState<ViewMode>("ALL");
  const [businessValueUsd, setBusinessValueUsd] = useState<number>(100);
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
  const [activeLease, setActiveLease] = useState<WorkerLease | null>(null);
  const [storageBackend, setStorageBackend] = useState<string>("sqlite");
  const [storageDiagnostics, setStorageDiagnostics] = useState<StorageDiagnostics | null>(null);
  const [systemReady, setSystemReady] = useState<boolean>(true);

  // Auto-dismiss status notification toast
  useEffect(() => {
    if (statusMessage) {
      const timer = setTimeout(() => {
        setStatusMessage(null);
      }, 5000);
      return () => clearTimeout(timer);
    }
  }, [statusMessage]);

  // Multi-tenant Security Context & Bearer Auth
  const [tenantId, setTenantId] = useState<string>(
    () => localStorage.getItem("argus_tenant_id") || "default_tenant"
  );
  const [workspaceId, setWorkspaceId] = useState<string>(
    () => localStorage.getItem("argus_workspace_id") || "default_workspace"
  );
  const [actorId, setActorId] = useState<string>(
    () => localStorage.getItem("argus_actor_id") || "operator_admin"
  );
  const [authToken, setAuthToken] = useState<string>(
    () => localStorage.getItem("argus_auth_token") || ""
  );

  const handleSaveAuthConfig = useCallback(
    (newTenant: string, newWorkspace: string, newActor: string, newToken: string) => {
      const validTenant = newTenant.trim() || "default_tenant";
      const validWorkspace = newWorkspace.trim() || "default_workspace";
      const validActor = newActor.trim() || "operator_admin";
      setTenantId(validTenant);
      setWorkspaceId(validWorkspace);
      setActorId(validActor);
      setAuthToken(newToken);
      localStorage.setItem("argus_tenant_id", validTenant);
      localStorage.setItem("argus_workspace_id", validWorkspace);
      localStorage.setItem("argus_actor_id", validActor);
      localStorage.setItem("argus_auth_token", newToken);
      setStatusMessage(`Updated context to ${validTenant} / ${validWorkspace} (${validActor})`);
    },
    []
  );

  const authFetch = useCallback(
    async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
      const headers = new Headers(init?.headers);
      if (authToken) {
        headers.set("Authorization", `Bearer ${authToken}`);
      }
      headers.set("X-Tenant-ID", tenantId);
      headers.set("X-Workspace-ID", workspaceId);
      headers.set("X-Actor-ID", actorId);
      return fetch(input, { ...init, headers });
    },
    [authToken, tenantId, workspaceId, actorId]
  );

  const selectedSession = sessions.find((s) => s.session_id === selectedSessionId) || null;

  const fetchCloudWatchLogs = useCallback(async () => {
    try {
      const res = await authFetch("/api/v1/telemetry/cloudwatch");
      if (res.ok) {
        const data: ContainerLog[] = await res.json();
        setLogs(data);
      }
    } catch {
      // Offline fallback
    }
  }, [authFetch]);

  const fetchSystemReadiness = useCallback(async () => {
    try {
      const res = await fetch("/readyz?diagnostics=true");
      if (res.ok) {
        const data: ReadyzResponse = await res.json();
        setSystemReady(data.status === "READY");
        if (data.storage_backend) setStorageBackend(data.storage_backend);
        if (data.diagnostics) setStorageDiagnostics(data.diagnostics);
      }
    } catch {
      // Offline fallback
    }
  }, []);

  const handleFlushWalCheckpoint = useCallback(async () => {
    try {
      const res = await authFetch("/api/v1/system/checkpoint", { method: "POST" });
      if (res.ok) {
        const data = await res.json();
        setStatusMessage(
          `WAL Checkpoint complete: ${data.checkpointed_frames ?? 0} frames committed to disk.`
        );
        await fetchSystemReadiness();
      } else {
        setStatusMessage("Checkpoint skipped or in-memory backend active.");
      }
    } catch {
      setStatusMessage("Failed to execute WAL checkpoint.");
    }
  }, [authFetch, fetchSystemReadiness]);

  const fetchBenchmarks = useCallback(
    async (targetModel?: string) => {
      try {
        const res = await authFetch("/api/v1/attribution/benchmarks/catalog");
        if (res.ok) {
          const data = await res.json();
          setBenchmarks(data);
        }
        const modelToEvaluate = targetModel || selectedSpan?.model_name || "claude-3-5-sonnet";
        const recRes = await authFetch("/api/v1/attribution/benchmarks/recommend", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            current_model: modelToEvaluate,
            min_acceptable_accuracy: 0.5,
          }),
        });
        if (recRes.ok) {
          const recData = await recRes.json();
          setRecommendations(recData);
        }
      } catch {
        // Offline fallback
      }
    },
    [authFetch, selectedSpan]
  );

  const fetchSessionDetails = useCallback(
    async (sessionId: string, assignedValue: number = businessValueUsd) => {
      try {
        const [spansRes, toolsRes, cpRes, auditRes, roiRes] = await Promise.all([
          authFetch(`/api/v1/telemetry/sessions/${sessionId}/spans`),
          authFetch(`/api/v1/c2/${sessionId}/pending-tools`),
          authFetch(`/api/v1/c2/${sessionId}/checkpoints/latest`),
          authFetch(`/api/v1/c2/${sessionId}/audit-log`),
          authFetch(
            `/api/v1/attribution/roi/${sessionId}?assigned_business_value_usd=${assignedValue}`
          ),
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

        try {
          const leaseRes = await authFetch(`/api/v1/c2/${sessionId}/lease`);
          if (leaseRes.ok) {
            const lData: WorkerLease = await leaseRes.json();
            setActiveLease(lData);
          } else {
            setActiveLease(null);
          }
        } catch {
          setActiveLease(null);
        }
      } catch {
        // Offline fallback
      }
    },
    [authFetch, businessValueUsd]
  );

  const handleSeedScenario = useCallback(async () => {
    setSeeding(true);
    setStatusMessage("Seeding multi-agent scenario...");
    try {
      const res = await authFetch("/api/v1/demo/seed", { method: "POST" });
      if (res.ok) {
        const data = await res.json();
        const sessRes = await authFetch("/api/v1/telemetry/sessions");
        if (sessRes.ok) {
          const sessList: AgentSession[] = await sessRes.json();
          setSessions(sessList);
        }
        await fetchCloudWatchLogs();
        const targetId = data.tripped_session_id || data.paused_c2_session_id;
        if (targetId) {
          setSelectedSessionId(targetId);
          await fetchSessionDetails(targetId);
        }
        setStatusMessage(
          "Initialized 3 agent scenarios (LangGraph Loop, CrewAI Paused Gate, AutoGPT FinOps)."
        );
      }
    } finally {
      setSeeding(false);
    }
  }, [authFetch, fetchCloudWatchLogs, fetchSessionDetails]);

  const fetchSessions = useCallback(async () => {
    try {
      const res = await authFetch("/api/v1/telemetry/sessions");
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
  }, [authFetch, selectedSessionId]);

  useEffect(() => {
    fetchSessions();
    fetchBenchmarks();
    fetchCloudWatchLogs();
    fetchSystemReadiness();
  }, [fetchSessions, fetchBenchmarks, fetchCloudWatchLogs, fetchSystemReadiness]);

  useEffect(() => {
    if (selectedSessionId) {
      fetchSessionDetails(selectedSessionId, businessValueUsd);
    }
  }, [selectedSessionId, businessValueUsd, fetchSessionDetails]);

  useEffect(() => {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const host = window.location.host;
    const tokenParam = authToken ? `&token=${encodeURIComponent(authToken)}` : "";
    const wsUrl = `${protocol}//${host}/ws/v1/stream?tenant_id=${encodeURIComponent(
      tenantId
    )}&workspace_id=${encodeURIComponent(workspaceId)}${tokenParam}`;

    let ws: WebSocket | null = null;
    let reconnectTimer: number | null = null;
    let pingInterval: number | null = null;

    const connect = () => {
      try {
        ws = new WebSocket(wsUrl);

        ws.onopen = () => {
          setWsConnected(true);
          pingInterval = window.setInterval(() => {
            if (ws && ws.readyState === WebSocket.OPEN) {
              ws.send(JSON.stringify({ action: "ping" }));
            }
          }, 25000);
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
              data.channel === "c2.override_resolved" ||
              data.channel === "c2.dead_man_switch_triggered" ||
              data.channel === "c2.lease_expired"
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
          if (pingInterval) clearInterval(pingInterval);
          reconnectTimer = window.setTimeout(connect, 3000);
        };

        ws.onerror = () => {
          setWsConnected(false);
          if (pingInterval) clearInterval(pingInterval);
          ws?.close();
        };
      } catch {
        setWsConnected(false);
        if (pingInterval) clearInterval(pingInterval);
        reconnectTimer = window.setTimeout(connect, 3000);
      }
    };

    connect();

    return () => {
      if (reconnectTimer) clearTimeout(reconnectTimer);
      if (pingInterval) clearInterval(pingInterval);
      ws?.close();
    };
  }, [fetchSessions, fetchSessionDetails, fetchCloudWatchLogs, selectedSessionId]);

  const handleSimulateLoopStep = async () => {
    if (!selectedSessionId) return;
    const res = await authFetch(
      `/api/v1/telemetry/otlp?default_session_id=${selectedSessionId}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          spans: [
            {
              name: "tool:query_orders_db",
              attributes: {
                "openinference.span.kind": "TOOL",
                "gen_ai.operation.name": "execute_tool",
                "argus.framework": selectedSession?.framework || "langgraph",
                "argus.cost.usd": 0.0025,
                tool_name: "query_orders_db",
                input_payload: JSON.stringify({
                  sql: "SELECT * FROM orders WHERE order_id = 'ORD-9941'",
                }),
                output_payload: JSON.stringify({
                  content: "Retrying identical SQL query on replica...",
                }),
              },
            },
          ],
        }),
      }
    );
    if (res.ok) {
      const data = await res.json();
      if (data.tripped_circuit_breaker) {
        setStatusMessage(
          `Circuit breaker tripped: ${data.warning || "Repetitive reasoning loop halted."}`
        );
      } else {
        setStatusMessage(
          "Injected identical tool span (click again to trip the circuit breaker)."
        );
      }
      fetchSessions();
      fetchSessionDetails(selectedSessionId);
    }
  };

  const handleSimulateMcpAttack = async () => {
    if (!selectedSessionId) return;
    const callId = `mcp_${Math.random().toString(36).substring(2, 8)}`;
    const res = await authFetch("/api/v1/governance/mcp/intercept", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: selectedSessionId,
        tool_call_id: callId,
        tool_name: "drop_production_ledger",
        tool_args: {
          schema: "billing_prod",
          cascade: true,
          note: "Simulated destructive MCP tool call",
        },
        estimated_cost_usd: 0.005,
        hard_cap_usd: 50.0,
      }),
    });
    if (res.ok) {
      setStatusMessage(
        `MCP Proxy intercepted destructive call [drop_production_ledger] (${callId}) and paused session for human authorization.`
      );
      fetchSessions();
      fetchSessionDetails(selectedSessionId);
    }
  };

  const handlePause = async (sessionId: string) => {
    const res = await authFetch(`/api/v1/c2/${sessionId}/pause`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        operator_id: actorId,
        reason: "Operator manual pause",
      }),
    });
    if (res.ok) {
      setStatusMessage(`Session ${sessionId.substring(0, 8)} paused.`);
      fetchSessions();
      if (selectedSessionId === sessionId) fetchSessionDetails(sessionId);
    }
  };

  const handleResume = async (sessionId: string) => {
    const res = await authFetch(`/api/v1/c2/${sessionId}/resume`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        operator_id: actorId,
        reason: "Operator resumed session",
      }),
    });
    if (res.ok) {
      setStatusMessage(`Session ${sessionId.substring(0, 8)} resumed.`);
      fetchSessions();
      if (selectedSessionId === sessionId) fetchSessionDetails(sessionId);
    }
  };

  const handleTerminate = async (sessionId: string) => {
    const res = await authFetch(`/api/v1/c2/${sessionId}/terminate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        operator_id: actorId,
        reason: "Operator terminated session",
      }),
    });
    if (res.ok) {
      setStatusMessage(`Session ${sessionId.substring(0, 8)} terminated.`);
      fetchSessions();
      if (selectedSessionId === sessionId) fetchSessionDetails(sessionId);
    }
  };

  const handleApproveTool = async (toolCallId: string) => {
    if (!selectedSessionId) return;
    const res = await authFetch(`/api/v1/c2/${selectedSessionId}/tool-override`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        tool_call_id: toolCallId,
        decision: "approve",
        operator_id: actorId,
        reason: "Operator approved tool execution",
      }),
    });
    if (res.ok) {
      setStatusMessage(`Tool call ${toolCallId} approved and verified.`);
      fetchSessionDetails(selectedSessionId);
    }
  };

  const handleEditTool = async (
    toolCallId: string,
    modifiedArgs: Record<string, unknown>
  ) => {
    if (!selectedSessionId) return;
    const res = await authFetch(`/api/v1/c2/${selectedSessionId}/tool-override`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        tool_call_id: toolCallId,
        decision: "edit",
        modified_args: modifiedArgs,
        operator_id: actorId,
        reason: "Operator sanitized tool parameters",
      }),
    });
    if (res.ok) {
      setStatusMessage(`Tool call ${toolCallId} updated with sanitized arguments.`);
      fetchSessionDetails(selectedSessionId);
    }
  };

  const handleMockTool = async (
    toolCallId: string,
    mockOutput: Record<string, unknown>
  ) => {
    if (!selectedSessionId) return;
    const res = await authFetch(`/api/v1/c2/${selectedSessionId}/tool-override`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        tool_call_id: toolCallId,
        decision: "mock",
        mock_output: mockOutput,
        operator_id: actorId,
        reason: "Injected mock fixture",
      }),
    });
    if (res.ok) {
      setStatusMessage(`Tool call ${toolCallId} resolved with synthetic mock response.`);
      fetchSessionDetails(selectedSessionId);
    }
  };

  const handleRejectTool = async (toolCallId: string, reason: string) => {
    if (!selectedSessionId) return;
    const res = await authFetch(`/api/v1/c2/${selectedSessionId}/tool-override`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        tool_call_id: toolCallId,
        decision: "reject",
        rejection_reason: reason,
        operator_id: actorId,
        reason: "Security policy guardrail rejection",
      }),
    });
    if (res.ok) {
      setStatusMessage(`Tool call ${toolCallId} rejected.`);
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

      const res = await authFetch(`/api/v1/c2/${selectedSessionId}/patch`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          operator_id: actorId,
          expected_parent_checkpoint_id: expectedCpId,
          patches: patches,
          reason: "RFC 6902 memory patch",
        }),
      });
      if (res.ok) {
        const newCp: CheckpointRecord = await res.json();
        setStatusMessage(
          `RFC 6902 patch applied. New checkpoint: ${newCp.checkpoint_id.substring(0, 8)}`
        );
        fetchSessions();
        fetchSessionDetails(selectedSessionId);
      } else {
        const err = await res.json();
        setStatusMessage(`Patch failed: ${err.detail || JSON.stringify(err)}`);
      }
    } catch {
      setStatusMessage("Invalid JSON Patch syntax.");
    }
  };

  const handleReapLeases = async () => {
    setStatusMessage("Triggering Dead-Man's Switch reaper sweep...");
    try {
      const res = await authFetch("/api/v1/c2/leases/reap", { method: "POST" });
      if (res.ok) {
        const data: ReapLeasesResponse = await res.json();
        setStatusMessage(
          `Dead-Man's Switch reaper completed: ${data.reaped_count} expired session(s) terminated.`
        );
        await fetchSessions();
        if (selectedSessionId) {
          await fetchSessionDetails(selectedSessionId);
        }
      } else {
        setStatusMessage("Failed to execute Dead-Man's Switch reaper sweep.");
      }
    } catch {
      setStatusMessage("Failed to execute Dead-Man's Switch reaper sweep.");
    }
  };

  return (
    <div className="flex flex-col min-h-screen bg-[#09090b] text-[#f4f4f5]">
      <Header
        wsConnected={wsConnected}
        sessions={sessions}
        pendingInterventionsCount={pendingTools.length}
        activeView={activeView}
        onSelectView={setActiveView}
        onSeedScenario={handleSeedScenario}
        onSimulateLoopStep={handleSimulateLoopStep}
        onSimulateMcpAttack={handleSimulateMcpAttack}
        seeding={seeding}
        hasSelectedSession={Boolean(selectedSessionId)}
        tenantId={tenantId}
        workspaceId={workspaceId}
        actorId={actorId}
        authToken={authToken}
        onSaveAuthConfig={handleSaveAuthConfig}
        storageBackend={storageBackend}
        storageDiagnostics={storageDiagnostics}
        systemReady={systemReady}
        onFlushWalCheckpoint={handleFlushWalCheckpoint}
      />

      <main className="flex-1 p-6 max-w-[1920px] w-full mx-auto">
        {/* VIEW: ALL (Executive Operations Overview) */}
        {activeView === "ALL" && (
          <div className="flex flex-col gap-6 w-full">
            {/* Top Deck: Fleet Active Roster & Live Logs side-by-side */}
            <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 w-full">
              <div className="lg:col-span-5 flex flex-col">
                <FleetOverview
                  sessions={sessions}
                  selectedSessionId={selectedSessionId}
                  onSelectSession={(id) => setSelectedSessionId(id)}
                  onPause={handlePause}
                  onResume={handleResume}
                  onTerminate={handleTerminate}
                  onSeedScenario={handleSeedScenario}
                />
              </div>
              <div className="lg:col-span-7 flex flex-col">
                <LogWaterfall logs={logs} />
              </div>
            </div>

            {/* Mid Deck: Execution DAG & Command & Control Lab */}
            <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 w-full">
              <div className="lg:col-span-6 flex flex-col">
                <LangGraphVisualizer
                  spans={spans}
                  selectedSpan={selectedSpan}
                  onSelectSpan={(span) => setSelectedSpan(span)}
                  authFetch={authFetch}
                />
              </div>
              <div className="lg:col-span-6 flex flex-col">
                <C2ControlPanel
                  sessionId={selectedSessionId}
                  sessionStatus={selectedSession?.status}
                  pendingTools={pendingTools}
                  latestCheckpoint={latestCheckpoint}
                  auditLog={auditLog}
                  statusMessage={statusMessage}
                  activeLease={activeLease}
                  onApproveTool={handleApproveTool}
                  onEditTool={handleEditTool}
                  onMockTool={handleMockTool}
                  onRejectTool={handleRejectTool}
                  onApplyPatch={handleApplyPatch}
                  onReapLeases={handleReapLeases}
                  authFetch={authFetch}
                />
              </div>
            </div>

            {/* Bottom Deck: FinOps & Pareto Intelligence */}
            <div className="w-full">
              <RoiAndBenchmarks
                roi={roi}
                benchmarks={benchmarks}
                recommendations={recommendations}
                businessValueUsd={businessValueUsd}
                onChangeBusinessValue={(val) => setBusinessValueUsd(val)}
              />
            </div>
          </div>
        )}

        {/* VIEW: TOPOLOGY (Full Canvas Execution Graph & Spans) */}
        {activeView === "TOPOLOGY" && (
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 w-full">
            <div className="lg:col-span-4 flex flex-col gap-6">
              <FleetOverview
                sessions={sessions}
                selectedSessionId={selectedSessionId}
                onSelectSession={(id) => setSelectedSessionId(id)}
                onPause={handlePause}
                onResume={handleResume}
                onTerminate={handleTerminate}
                onSeedScenario={handleSeedScenario}
              />
              <LogWaterfall logs={logs} />
            </div>
            <div className="lg:col-span-8 flex flex-col">
              <LangGraphVisualizer
                spans={spans}
                selectedSpan={selectedSpan}
                onSelectSpan={(span) => setSelectedSpan(span)}
                authFetch={authFetch}
              />
            </div>
          </div>
        )}

        {/* VIEW: C2_LAB (Command & Control Interventions & Ledger) */}
        {activeView === "C2_LAB" && (
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 w-full">
            <div className="lg:col-span-4 flex flex-col">
              <FleetOverview
                sessions={sessions}
                selectedSessionId={selectedSessionId}
                onSelectSession={(id) => setSelectedSessionId(id)}
                onPause={handlePause}
                onResume={handleResume}
                onTerminate={handleTerminate}
                onSeedScenario={handleSeedScenario}
              />
            </div>
            <div className="lg:col-span-8 flex flex-col">
              <C2ControlPanel
                sessionId={selectedSessionId}
                sessionStatus={selectedSession?.status}
                pendingTools={pendingTools}
                latestCheckpoint={latestCheckpoint}
                auditLog={auditLog}
                statusMessage={statusMessage}
                activeLease={activeLease}
                onApproveTool={handleApproveTool}
                onEditTool={handleEditTool}
                onMockTool={handleMockTool}
                onRejectTool={handleRejectTool}
                onApplyPatch={handleApplyPatch}
                onReapLeases={handleReapLeases}
                authFetch={authFetch}
              />
            </div>
          </div>
        )}

        {/* VIEW: FINOPS (Executive ROI & Pareto Benchmark Intelligence) */}
        {activeView === "FINOPS" && (
          <div className="max-w-7xl mx-auto w-full flex flex-col">
            <RoiAndBenchmarks
              roi={roi}
              benchmarks={benchmarks}
              recommendations={recommendations}
              businessValueUsd={businessValueUsd}
              onChangeBusinessValue={(val) => setBusinessValueUsd(val)}
            />
          </div>
        )}
      </main>

      {/* Floating Status Notification Toast */}
      {statusMessage && (() => {
        const lower = statusMessage.toLowerCase();
        const isError =
          lower.includes("failed") ||
          lower.includes("error") ||
          lower.includes("reject") ||
          lower.includes("terminat");
        const isWarning =
          lower.includes("warn") ||
          lower.includes("pause") ||
          lower.includes("unauthoriz");

        const dotClass = isError
          ? "bg-rose-400"
          : isWarning
          ? "bg-amber-400"
          : "bg-emerald-400";
        const borderClass = isError
          ? "border-rose-500/40 bg-[#161014]/95"
          : isWarning
          ? "border-amber-500/40 bg-[#161410]/95"
          : "border-[#2e2e38] bg-[#141418]/95";

        return (
          <div
            className={`fixed bottom-6 right-6 z-50 flex items-center gap-3 rounded-lg border ${borderClass} px-4 py-3 text-xs text-zinc-100 shadow-2xl backdrop-blur-md transition-all animate-in fade-in slide-in-from-bottom-2`}
          >
            <span className={`h-2 w-2 rounded-full ${dotClass} shrink-0`} />
            <span className="font-mono text-[11px] max-w-md leading-relaxed">
              {statusMessage}
            </span>
            <button
              onClick={() => setStatusMessage(null)}
              className="text-zinc-500 hover:text-zinc-200 p-0.5 rounded cursor-pointer transition-colors"
              title="Dismiss notification"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        );
      })()}

      {/* Utilitarian Footer */}
      <footer className="border-t border-[#222228] bg-[#09090b] px-6 py-3 flex flex-wrap justify-between items-center gap-4 text-[11px] text-zinc-500 font-mono">
        <div className="flex items-center gap-2">
          <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
          <span className="text-zinc-400 font-sans font-medium">Argus AgentOps C2</span>
          <span className="text-zinc-600">•</span>
          <span>v0.1.0-alpha</span>
          <span className="text-zinc-600">•</span>
          <span>$0 Open-Source Core</span>
        </div>
        <div className="flex items-center gap-4 text-zinc-500">
          <span>OTel GenAI</span>
          <span>•</span>
          <span>Arize Phoenix</span>
          <span>•</span>
          <span>LangGraph</span>
          <span>•</span>
          <span>RFC 6902</span>
          <span>•</span>
          <span>SHA-256 Ledger</span>
        </div>
      </footer>
    </div>
  );
};
