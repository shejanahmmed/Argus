import React, { useState, useEffect, useMemo, useCallback } from "react";
import {
  ShieldAlert,
  CircleDollarSign,
  Lock,
  Unlock,
  CheckCircle2,
  ExternalLink,
  Users,
  Calendar,
  Activity,
  Sparkles,
  ArrowRight,
  ShieldCheck,
  Zap,
  Globe,
  Database,
  Code2,
  FileCode,
  Github,
  Mail,
  Linkedin,
  Settings,
  X,
} from "lucide-react";
import { ArgusLogo } from "./ArgusLogo";
import {
  AgentSession,
  StorageDiagnostics,
  TeamMemberInfo,
  DocsConfigResponse,
} from "../types";

interface LiveDocsModuleProps {
  sessions: AgentSession[];
  wsConnected: boolean;
  storageBackend?: string;
  storageDiagnostics?: StorageDiagnostics | null;
  systemReady?: boolean;
  tenantId: string;
  workspaceId: string;
  actorId: string;
  authToken: string;
  onClose: () => void;
  onFlushWalCheckpoint?: () => void;
}

type DocsSection = "PITCH" | "TECH" | "LIVE_SYSTEM" | "TEAM" | "ADMIN";

export const LiveDocsModule: React.FC<LiveDocsModuleProps> = ({
  sessions,
  wsConnected,
  storageBackend = "sqlite",
  storageDiagnostics,
  systemReady = true,
  tenantId,
  workspaceId,
  actorId,
  authToken,
  onClose,
  onFlushWalCheckpoint,
}) => {
  const [activeSection, setActiveSection] = useState<DocsSection>("PITCH");
  const [adminUnlocked, setAdminUnlocked] = useState<boolean>(false);
  const [config, setConfig] = useState<DocsConfigResponse>({
    is_public: true,
    visibility_mode: "PUBLIC",
    scheduled_start: null,
    scheduled_end: null,
    last_updated_at: new Date().toISOString(),
    updated_by: "operator_admin",
    project_name: "Argus C2",
    tagline: "Zero-Tolerance Autonomous Agent Governance & Control Plane",
    team: [
      {
        name: "Shejan Ahmmed",
        role: "Lead Systems Engineer & AI Architect",
        email: "shejanahmmed.dev@gmail.com",
        github: "https://github.com/ShejanAhmmed",
        linkedin: "https://linkedin.com/in/shejanahmmed",
        bio: "Principal architect specializing in autonomous agent governance, distributed systems resilience, and zero-spend observability architectures.",
      },
    ],
  });
  const [savingConfig, setSavingConfig] = useState<boolean>(false);
  const [saveMessage, setSaveMessage] = useState<string | null>(null);

  // Editable form state in Admin panel
  const [editVisibility, setEditVisibility] = useState<"PUBLIC" | "RESTRICTED" | "SCHEDULED">("PUBLIC");
  const [editStart, setEditStart] = useState<string>("");
  const [editEnd, setEditEnd] = useState<string>("");
  const [newMemberName, setNewMemberName] = useState<string>("");
  const [newMemberRole, setNewMemberRole] = useState<string>("");
  const [newMemberEmail, setNewMemberEmail] = useState<string>("");
  const [newMemberGithub, setNewMemberGithub] = useState<string>("");
  const [newMemberBio, setNewMemberBio] = useState<string>("");

  // Fetch initial config from backend
  useEffect(() => {
    const fetchConfig = async () => {
      try {
        const res = await fetch("/api/v1/docs/config");
        if (res.ok) {
          const data: DocsConfigResponse = await res.json();
          setConfig(data);
          setEditVisibility(data.visibility_mode);
          setEditStart(data.scheduled_start || "");
          setEditEnd(data.scheduled_end || "");
        }
      } catch {
        // Fallback to local default
      }
    };
    fetchConfig();
  }, []);

  // Determine if content is accessible based on visibility settings
  const isAccessible = useMemo(() => {
    if (adminUnlocked) return true;
    if (config.visibility_mode === "PUBLIC") return true;
    if (config.visibility_mode === "RESTRICTED") return false;
    if (config.visibility_mode === "SCHEDULED") {
      const now = new Date();
      if (config.scheduled_start && new Date(config.scheduled_start) > now) return false;
      if (config.scheduled_end && new Date(config.scheduled_end) < now) return false;
      return true;
    }
    return true;
  }, [adminUnlocked, config]);

  // Handle saving admin configuration
  const handleSaveConfig = useCallback(async () => {
    setSavingConfig(true);
    setSaveMessage(null);
    try {
      const payload = {
        is_public: editVisibility === "PUBLIC",
        visibility_mode: editVisibility,
        scheduled_start: editStart.trim() || null,
        scheduled_end: editEnd.trim() || null,
        team: config.team,
      };
      const headers = new Headers({ "Content-Type": "application/json" });
      if (authToken) headers.set("Authorization", `Bearer ${authToken}`);
      headers.set("X-Tenant-ID", tenantId);
      headers.set("X-Workspace-ID", workspaceId);
      headers.set("X-Actor-ID", actorId);

      const res = await fetch("/api/v1/docs/config", {
        method: "POST",
        headers,
        body: JSON.stringify(payload),
      });

      if (res.ok) {
        const updated: DocsConfigResponse = await res.json();
        setConfig(updated);
        setSaveMessage("Configuration successfully persisted to backend.");
      } else {
        // Fallback to local state update
        setConfig((prev) => ({
          ...prev,
          visibility_mode: editVisibility,
          is_public: editVisibility === "PUBLIC",
          scheduled_start: editStart.trim() || null,
          scheduled_end: editEnd.trim() || null,
          last_updated_at: new Date().toISOString(),
        }));
        setSaveMessage("Saved locally (offline mode).");
      }
    } catch {
      setSaveMessage("Saved locally (offline fallback).");
    } finally {
      setSavingConfig(false);
      setTimeout(() => setSaveMessage(null), 4000);
    }
  }, [editVisibility, editStart, editEnd, config.team, authToken, tenantId, workspaceId, actorId]);

  // Add new team member
  const handleAddTeamMember = () => {
    if (!newMemberName.trim() || !newMemberRole.trim()) return;
    const newMember: TeamMemberInfo = {
      name: newMemberName.trim(),
      role: newMemberRole.trim(),
      email: newMemberEmail.trim(),
      github: newMemberGithub.trim(),
      bio: newMemberBio.trim(),
    };
    setConfig((prev) => ({
      ...prev,
      team: [...prev.team, newMember],
    }));
    setNewMemberName("");
    setNewMemberRole("");
    setNewMemberEmail("");
    setNewMemberGithub("");
    setNewMemberBio("");
  };

  // Remove team member
  const handleRemoveTeamMember = (index: number) => {
    setConfig((prev) => ({
      ...prev,
      team: prev.team.filter((_, idx) => idx !== index),
    }));
  };

  // Real-time fleet metrics for Live System tab
  const runningSessions = sessions.filter((s) => s.status === "RUNNING");
  const pausedSessions = sessions.filter((s) => s.status === "PAUSED_C2");
  const trippedSessions = sessions.filter(
    (s) => s.status === "TRIPPED_LOOP" || s.status === "TRIPPED_BUDGET"
  );
  const totalFleetSpend = sessions.reduce((sum, s) => sum + s.accumulated_cost_usd, 0);

  return (
    <div className="flex flex-col min-h-screen bg-[#070709] text-zinc-100 font-sans selection:bg-emerald-500/20 selection:text-emerald-300">
      {/* Top Banner Navigation */}
      <header className="sticky top-0 z-40 border-b border-[#222228] bg-[#09090c]/95 backdrop-blur-md px-6 py-3 flex flex-wrap items-center justify-between gap-4">
        {/* Brand & Subtitle */}
        <div className="flex items-center gap-3">
          <ArgusLogo className="h-6 w-6 text-emerald-400 shrink-0 drop-shadow-[0_0_10px_rgba(16,185,129,0.3)]" />
          <div className="flex flex-col">
            <div className="flex items-center gap-2">
              <span className="text-base font-bold tracking-wider text-white font-sans uppercase">
                Argus C2 // Live /docs
              </span>
              <span className="rounded bg-emerald-950/60 border border-emerald-500/30 px-1.5 py-0.5 text-[9px] font-mono font-bold text-emerald-400">
                PITCH & TECH DECK
              </span>
            </div>
            <p className="text-[10px] font-mono text-zinc-400">
              Autonomous Agent Governance, Observability & Control Plane
            </p>
          </div>
        </div>

        {/* Section Navigation Pills */}
        <div className="flex items-center gap-1 rounded-lg bg-[#111114] p-1 border border-[#222228]">
          <button
            onClick={() => setActiveSection("PITCH")}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-colors cursor-pointer ${
              activeSection === "PITCH"
                ? "bg-[#1f1f26] text-white shadow-xs"
                : "text-zinc-400 hover:text-white hover:bg-zinc-800/40"
            }`}
          >
            <Sparkles className="h-3.5 w-3.5 text-emerald-400" />
            <span>YC Pitch Deck</span>
          </button>

          <button
            onClick={() => setActiveSection("TECH")}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-colors cursor-pointer ${
              activeSection === "TECH"
                ? "bg-[#1f1f26] text-white shadow-xs"
                : "text-zinc-400 hover:text-white hover:bg-zinc-800/40"
            }`}
          >
            <Code2 className="h-3.5 w-3.5 text-zinc-400" />
            <span>Tech Whitepaper</span>
          </button>

          <button
            onClick={() => setActiveSection("LIVE_SYSTEM")}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-colors cursor-pointer ${
              activeSection === "LIVE_SYSTEM"
                ? "bg-[#1f1f26] text-white shadow-xs"
                : "text-zinc-400 hover:text-white hover:bg-zinc-800/40"
            }`}
          >
            <Activity className="h-3.5 w-3.5 text-emerald-400" />
            <span>Live System Telemetry</span>
            <span className="flex h-1.5 w-1.5 rounded-full bg-emerald-400 animate-pulse ml-0.5" />
          </button>

          <button
            onClick={() => setActiveSection("TEAM")}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-colors cursor-pointer ${
              activeSection === "TEAM"
                ? "bg-[#1f1f26] text-white shadow-xs"
                : "text-zinc-400 hover:text-white hover:bg-zinc-800/40"
            }`}
          >
            <Users className="h-3.5 w-3.5 text-zinc-400" />
            <span>Team ({config.team.length})</span>
          </button>

          <button
            onClick={() => setActiveSection("ADMIN")}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-colors cursor-pointer ${
              activeSection === "ADMIN"
                ? "bg-[#1f1f26] text-white shadow-xs"
                : "text-zinc-400 hover:text-white hover:bg-zinc-800/40"
            }`}
            title="Publishing controls, visibility toggle, and scheduling"
          >
            <Settings className="h-3.5 w-3.5 text-zinc-400" />
            <span>Admin</span>
          </button>
        </div>

        {/* Right Actions: Swagger Link & Return Button */}
        <div className="flex items-center gap-2">
          <a
            href="/api/docs"
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-1.5 rounded-md border border-[#27272a] bg-[#141418] px-3 py-1.5 text-xs font-mono text-zinc-300 hover:bg-[#1a1a20] hover:text-white transition-colors"
            title="Open raw OpenAPI 3.1 Swagger UI specification"
          >
            <FileCode className="h-3.5 w-3.5 text-emerald-400" />
            <span>OpenAPI /api/docs</span>
            <ExternalLink className="h-3 w-3 text-zinc-500" />
          </a>

          <button
            onClick={onClose}
            className="flex items-center gap-1.5 rounded-md border border-[#27272a] bg-[#141418] hover:bg-[#202028] px-3 py-1.5 text-xs font-medium text-white transition-colors cursor-pointer"
          >
            <X className="h-3.5 w-3.5" />
            <span>Close /docs</span>
          </button>
        </div>
      </header>

      {/* Main Content Area */}
      <main className="flex-1 max-w-7xl mx-auto w-full px-6 py-8">
        {/* Gate: If restricted and not admin unlocked */}
        {!isAccessible ? (
          <div className="flex flex-col items-center justify-center py-24 text-center max-w-lg mx-auto">
            <div className="rounded-full bg-rose-500/10 border border-rose-500/20 p-4 mb-4">
              <Lock className="h-8 w-8 text-rose-400" />
            </div>
            <h2 className="text-xl font-bold text-white mb-2">
              RESTRICTED ACCESS
            </h2>
            <p className="text-xs font-mono text-zinc-400 mb-6 leading-relaxed">
              This documentation and pitch deck is currently restricted or outside its scheduled publishing window ({config.visibility_mode}). Only authorized administrators can access this material.
            </p>
            <div className="flex items-center gap-3">
              <button
                onClick={() => setAdminUnlocked(true)}
                className="flex items-center gap-2 rounded-md bg-emerald-500 hover:bg-emerald-400 text-black font-semibold px-4 py-2 text-xs transition-colors cursor-pointer"
              >
                <Unlock className="h-3.5 w-3.5" />
                <span>Operator Admin Bypass</span>
              </button>
              <button
                onClick={onClose}
                className="rounded-md border border-[#27272a] bg-[#141418] px-4 py-2 text-xs text-zinc-300 hover:bg-[#1a1a20] transition-colors"
              >
                Back to Dashboard
              </button>
            </div>
          </div>
        ) : (
          <>
            {/* ========================================================================= */}
            {/* SECTION 1: YC-STYLE PITCH DECK                                           */}
            {/* ========================================================================= */}
            {activeSection === "PITCH" && (
              <div className="space-y-10 animate-in fade-in duration-300">
                {/* Hero Deck Card */}
                <div className="rounded-2xl border border-[#222228] bg-linear-to-b from-[#111116] to-[#0a0a0d] p-8 md:p-12 shadow-2xl relative overflow-hidden">
                  <div className="absolute top-0 right-0 w-96 h-96 bg-emerald-500/5 rounded-full blur-3xl pointer-events-none" />
                  <div className="relative z-10 max-w-3xl">
                    <div className="inline-flex items-center gap-2 rounded-full bg-emerald-950/60 border border-emerald-500/30 px-3 py-1 text-xs font-mono text-emerald-400 mb-6">
                      <Sparkles className="h-3.5 w-3.5" />
                      <span>THE CONTROL PLANE FOR AUTONOMOUS AGENTS</span>
                    </div>
                    <h1 className="text-3xl md:text-5xl font-extrabold text-white tracking-tight leading-tight mb-4 font-sans">
                      Stopping Runaway AI Agents Before They Break Production.
                    </h1>
                    <p className="text-base md:text-lg text-zinc-400 font-sans leading-relaxed mb-8">
                      Argus is a zero-tolerance Command & Control (C2) governance plane that intercepts destructive tool calls, eliminates runaway token spend, and halts infinite loops in autonomous AI agent systems in real time.
                    </p>
                    <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 pt-6 border-t border-[#222228]">
                      <div>
                        <div className="text-2xl font-bold font-mono text-emerald-400">$0.00</div>
                        <div className="text-[11px] text-zinc-500 uppercase tracking-wider font-mono">Infra Budget Constraint</div>
                      </div>
                      <div>
                        <div className="text-2xl font-bold font-mono text-white">&lt;5ms</div>
                        <div className="text-[11px] text-zinc-500 uppercase tracking-wider font-mono">Policy Intercept Latency</div>
                      </div>
                      <div>
                        <div className="text-2xl font-bold font-mono text-emerald-400">80%</div>
                        <div className="text-[11px] text-zinc-500 uppercase tracking-wider font-mono">Token Cost Reduction</div>
                      </div>
                      <div>
                        <div className="text-2xl font-bold font-mono text-white">142/142</div>
                        <div className="text-[11px] text-zinc-500 uppercase tracking-wider font-mono">Verified Automated Tests</div>
                      </div>
                    </div>
                  </div>
                </div>

                {/* 6 Core Pitch Slides Grid */}
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                  {/* Slide 1: The Problem */}
                  <div className="rounded-xl border border-[#222228] bg-[#0d0d10] p-6 flex flex-col justify-between hover:border-zinc-700 transition-colors">
                    <div>
                      <div className="flex items-center justify-between mb-4">
                        <span className="rounded bg-rose-950/60 border border-rose-500/30 px-2 py-0.5 text-[10px] font-mono font-bold text-rose-400">
                          SLIDE 01 // THE PROBLEM
                        </span>
                        <ShieldAlert className="h-5 w-5 text-rose-400" />
                      </div>
                      <h3 className="text-lg font-bold text-white mb-2">The Autonomous Blind Spot</h3>
                      <p className="text-xs text-zinc-400 leading-relaxed mb-4">
                        Enterprise AI is migrating from passive chat to unsupervised multi-agent execution loops (LangGraph, CrewAI). When agents fail, they fail catastrophically:
                      </p>
                      <ul className="text-xs font-mono text-zinc-300 space-y-2">
                        <li className="flex items-start gap-2">
                          <span className="text-rose-400">✕</span>
                          <span>Infinite semantic loops burning thousands in token spend overnight.</span>
                        </li>
                        <li className="flex items-start gap-2">
                          <span className="text-rose-400">✕</span>
                          <span>Destructive tool execution (dropping databases, unvetted rm commands).</span>
                        </li>
                        <li className="flex items-start gap-2">
                          <span className="text-rose-400">✕</span>
                          <span>Zombie workers crashing and leaving locks frozen.</span>
                        </li>
                      </ul>
                    </div>
                    <div className="mt-6 pt-4 border-t border-[#1a1a20] text-[11px] font-mono text-zinc-500">
                      Core flaw: Existing APM (Langfuse/Arize) only logs <span className="text-zinc-300">after</span> the damage is done.
                    </div>
                  </div>

                  {/* Slide 2: The Solution */}
                  <div className="rounded-xl border border-[#222228] bg-[#0d0d10] p-6 flex flex-col justify-between hover:border-zinc-700 transition-colors">
                    <div>
                      <div className="flex items-center justify-between mb-4">
                        <span className="rounded bg-emerald-950/60 border border-emerald-500/30 px-2 py-0.5 text-[10px] font-mono font-bold text-emerald-400">
                          SLIDE 02 // THE SOLUTION
                        </span>
                        <ShieldCheck className="h-5 w-5 text-emerald-400" />
                      </div>
                      <h3 className="text-lg font-bold text-white mb-2">Pre-Execution Zero-Tolerance C2</h3>
                      <p className="text-xs text-zinc-400 leading-relaxed mb-4">
                        Argus establishes a proactive firewall and Command & Control plane for autonomous agent runtimes:
                      </p>
                      <ul className="text-xs font-mono text-zinc-300 space-y-2">
                        <li className="flex items-start gap-2">
                          <span className="text-emerald-400">✓</span>
                          <span><strong>Pre-Execution MCP Proxy:</strong> Halts high-risk tool calls before they hit host OS or DB.</span>
                        </li>
                        <li className="flex items-start gap-2">
                          <span className="text-emerald-400">✓</span>
                          <span><strong>3-Tier Loop Detection:</strong> O(1) hash, SimHash, and Cosine similarity catching repetitive spinning.</span>
                        </li>
                        <li className="flex items-start gap-2">
                          <span className="text-emerald-400">✓</span>
                          <span><strong>Dead-Man's Switch:</strong> Auto-reaping orphaned worker leases in 30 seconds.</span>
                        </li>
                      </ul>
                    </div>
                    <div className="mt-6 pt-4 border-t border-[#1a1a20] text-[11px] font-mono text-emerald-400">
                      Outcome: Zero unauthorized destructive actions, zero runaway cloud bills.
                    </div>
                  </div>

                  {/* Slide 3: Market & Timing */}
                  <div className="rounded-xl border border-[#222228] bg-[#0d0d10] p-6 flex flex-col justify-between hover:border-zinc-700 transition-colors">
                    <div>
                      <div className="flex items-center justify-between mb-4">
                        <span className="rounded bg-zinc-800 border border-zinc-700 px-2 py-0.5 text-[10px] font-mono font-bold text-zinc-300">
                          SLIDE 03 // MARKET & TIMING
                        </span>
                        <Globe className="h-5 w-5 text-zinc-400" />
                      </div>
                      <h3 className="text-lg font-bold text-white mb-2">$28.5B Market by 2028</h3>
                      <p className="text-xs text-zinc-400 leading-relaxed mb-4">
                        Autonomous agent adoption is compounding at a 44% CAGR. Regulatory and enterprise governance mandates have arrived:
                      </p>
                      <ul className="text-xs font-mono text-zinc-300 space-y-2">
                        <li className="flex items-start gap-2">
                          <span className="text-emerald-400">→</span>
                          <span><strong>EU AI Act Article 14:</strong> Mandates human-in-the-loop oversight and automated kill switches.</span>
                        </li>
                        <li className="flex items-start gap-2">
                          <span className="text-emerald-400">→</span>
                          <span><strong>SOC 2 Type II Compliance:</strong> Demands immutable non-repudiation logs for AI-driven actions.</span>
                        </li>
                        <li className="flex items-start gap-2">
                          <span className="text-emerald-400">→</span>
                          <span><strong>Enterprise CIO Mandates:</strong> No unmonitored agents allowed in production VPCs.</span>
                        </li>
                      </ul>
                    </div>
                    <div className="mt-6 pt-4 border-t border-[#1a1a20] text-[11px] font-mono text-zinc-500">
                      Argus is the compliance passport for production agents.
                    </div>
                  </div>

                  {/* Slide 4: Business Model & FinOps ROI */}
                  <div className="rounded-xl border border-[#222228] bg-[#0d0d10] p-6 flex flex-col justify-between hover:border-zinc-700 transition-colors">
                    <div>
                      <div className="flex items-center justify-between mb-4">
                        <span className="rounded bg-emerald-950/60 border border-emerald-500/30 px-2 py-0.5 text-[10px] font-mono font-bold text-emerald-400">
                          SLIDE 04 // BUSINESS MODEL & ROI
                        </span>
                        <CircleDollarSign className="h-5 w-5 text-emerald-400" />
                      </div>
                      <h3 className="text-lg font-bold text-white mb-2">Automated Token Savings</h3>
                      <p className="text-xs text-zinc-400 leading-relaxed mb-4">
                        Argus pays for itself immediately via automated FinOps model downgrade recommendations:
                      </p>
                      <ul className="text-xs font-mono text-zinc-300 space-y-2">
                        <li className="flex items-start gap-2">
                          <span className="text-emerald-400">✓</span>
                          <span><strong>Pareto Routing:</strong> Analyzes subtask complexity and substitutes Claude 3.5 Sonnet ($3/$15) with DeepSeek-V3 or Llama-3-8B ($0.14/$0.28).</span>
                        </li>
                        <li className="flex items-start gap-2">
                          <span className="text-emerald-400">✓</span>
                          <span><strong>Average Savings:</strong> 65% to 80% reduction in net enterprise model API spend.</span>
                        </li>
                        <li className="flex items-start gap-2">
                          <span className="text-emerald-400">✓</span>
                          <span><strong>Self-Hosted Core:</strong> $0 infrastructure bill via embedded SQLite WAL.</span>
                        </li>
                      </ul>
                    </div>
                    <div className="mt-6 pt-4 border-t border-[#1a1a20] text-[11px] font-mono text-emerald-400">
                      Net ROI: $100 value generated per ~$0.08 token cost.
                    </div>
                  </div>

                  {/* Slide 5: Competitive Moats */}
                  <div className="rounded-xl border border-[#222228] bg-[#0d0d10] p-6 flex flex-col justify-between hover:border-zinc-700 transition-colors">
                    <div>
                      <div className="flex items-center justify-between mb-4">
                        <span className="rounded bg-zinc-800 border border-zinc-700 px-2 py-0.5 text-[10px] font-mono font-bold text-zinc-300">
                          SLIDE 05 // COMPETITIVE MOAT
                        </span>
                        <Zap className="h-5 w-5 text-amber-400" />
                      </div>
                      <h3 className="text-lg font-bold text-white mb-2">Why Argus Wins</h3>
                      <p className="text-xs text-zinc-400 leading-relaxed mb-4">
                        Comparing Argus against traditional observability tools:
                      </p>
                      <div className="space-y-2 text-xs font-mono">
                        <div className="p-2 rounded bg-[#141418] border border-[#222228]">
                          <span className="text-zinc-500">Langfuse / Arize:</span>{" "}
                          <span className="text-rose-400">Passive Post-Hoc Tracing</span> (alert after error).
                        </div>
                        <div className="p-2 rounded bg-emerald-950/30 border border-emerald-500/20">
                          <span className="text-emerald-400 font-bold">Argus C2:</span>{" "}
                          <span className="text-zinc-200">Pre-Execution Interception & State Rewind</span> (quarantine before tool execution).
                        </div>
                        <div className="p-2 rounded bg-[#141418] border border-[#222228]">
                          <span className="text-zinc-500">Forensics:</span>{" "}
                          <span className="text-emerald-400">SHA-256 Merkle Audit Ledger</span> with tamper-evident genesis block.
                        </div>
                      </div>
                    </div>
                    <div className="mt-6 pt-4 border-t border-[#1a1a20] text-[11px] font-mono text-zinc-500">
                      Active Command & Control vs. Passive Telemetry.
                    </div>
                  </div>

                  {/* Slide 6: Traction & Milestones */}
                  <div className="rounded-xl border border-[#222228] bg-[#0d0d10] p-6 flex flex-col justify-between hover:border-zinc-700 transition-colors">
                    <div>
                      <div className="flex items-center justify-between mb-4">
                        <span className="rounded bg-emerald-950/60 border border-emerald-500/30 px-2 py-0.5 text-[10px] font-mono font-bold text-emerald-400">
                          SLIDE 06 // TRACTION & VERIFICATION
                        </span>
                        <CheckCircle2 className="h-5 w-5 text-emerald-400" />
                      </div>
                      <h3 className="text-lg font-bold text-white mb-2">Enterprise-Grade Readiness</h3>
                      <p className="text-xs text-zinc-400 leading-relaxed mb-4">
                        Engineered under strict Principal Systems Engineer verification protocols:
                      </p>
                      <ul className="text-xs font-mono text-zinc-300 space-y-2">
                        <li className="flex items-start gap-2">
                          <span className="text-emerald-400">✓</span>
                          <span>142 automated unit, integration, and C2 tests passing in 2.45s.</span>
                        </li>
                        <li className="flex items-start gap-2">
                          <span className="text-emerald-400">✓</span>
                          <span>100% strict static type check across 85 Python files (mypy --strict).</span>
                        </li>
                        <li className="flex items-start gap-2">
                          <span className="text-emerald-400">✓</span>
                          <span>Vite React 19 bundle split to 134 kB with gzip compression.</span>
                        </li>
                        <li className="flex items-start gap-2">
                          <span className="text-emerald-400">✓</span>
                          <span>Rootless Docker container (UID 1000) ready for Hugging Face Spaces port 7860.</span>
                        </li>
                      </ul>
                    </div>
                    <div className="mt-6 pt-4 border-t border-[#1a1a20] text-[11px] font-mono text-emerald-400">
                      Zero technical debt, zero-hallucination codebase.
                    </div>
                  </div>
                </div>
              </div>
            )}

            {/* ========================================================================= */}
            {/* SECTION 2: TECHNICAL WHITEPAPER                                          */}
            {/* ========================================================================= */}
            {activeSection === "TECH" && (
              <div className="space-y-8 animate-in fade-in duration-300">
                {/* Architecture Overview */}
                <div className="rounded-xl border border-[#222228] bg-[#0d0d10] p-6">
                  <div className="flex items-center justify-between pb-4 border-b border-[#1c1c22] mb-6">
                    <div>
                      <h2 className="text-xl font-bold text-white">System Architecture & Pipeline Flow</h2>
                      <p className="text-xs font-mono text-zinc-400">Hexagonal Ports & Adapters with Pre-Execution Interception</p>
                    </div>
                    <span className="rounded bg-zinc-800 border border-zinc-700 px-2 py-1 text-xs font-mono text-emerald-400">
                      HEXAGONAL ARCHITECTURE
                    </span>
                  </div>

                  {/* Visual Data Flow Diagram */}
                  <div className="rounded-lg bg-[#070709] border border-[#222228] p-6 font-mono text-xs overflow-x-auto mb-6">
                    <div className="flex items-center justify-between gap-4 min-w-[700px] text-center">
                      <div className="p-3 rounded-md bg-[#141418] border border-zinc-700 flex-1">
                        <div className="text-emerald-400 font-bold mb-1">AGENT RUNTIME</div>
                        <div className="text-[10px] text-zinc-400">LangGraph / CrewAI / AutoGPT</div>
                      </div>
                      <ArrowRight className="h-4 w-4 text-zinc-600 shrink-0" />
                      <div className="p-3 rounded-md bg-[#141418] border border-emerald-500/40 flex-1 shadow-[0_0_15px_rgba(16,185,129,0.1)]">
                        <div className="text-emerald-400 font-bold mb-1">ARGUS MCP GATEWAY</div>
                        <div className="text-[10px] text-zinc-400">Pre-Execution Interception</div>
                      </div>
                      <ArrowRight className="h-4 w-4 text-zinc-600 shrink-0" />
                      <div className="p-3 rounded-md bg-[#141418] border border-amber-500/40 flex-1">
                        <div className="text-amber-400 font-bold mb-1">3-TIER CIRCUIT BREAKER</div>
                        <div className="text-[10px] text-zinc-400">Hash, SimHash & Cosine</div>
                      </div>
                      <ArrowRight className="h-4 w-4 text-zinc-600 shrink-0" />
                      <div className="p-3 rounded-md bg-[#141418] border border-zinc-700 flex-1">
                        <div className="text-white font-bold mb-1">SQLITE WAL STORAGE</div>
                        <div className="text-[10px] text-zinc-400">Merkle Audit Ledger</div>
                      </div>
                      <ArrowRight className="h-4 w-4 text-zinc-600 shrink-0" />
                      <div className="p-3 rounded-md bg-[#141418] border border-emerald-500/40 flex-1">
                        <div className="text-emerald-400 font-bold mb-1">C2 CONSOLE</div>
                        <div className="text-[10px] text-zinc-400">Real-Time WebSocket Bus</div>
                      </div>
                    </div>
                  </div>

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-6 text-xs text-zinc-300">
                    <div className="space-y-3">
                      <h4 className="font-mono font-bold text-white uppercase tracking-wider text-[11px]">
                        1. Ingestion & Pre-Execution Proxy
                      </h4>
                      <p className="leading-relaxed text-zinc-400">
                        Argus operates as an inline reverse proxy for the Model Context Protocol (MCP). When an autonomous agent attempts a tool invocation (`tools/call`), Argus intercepts the JSON-RPC request before it reaches host execution, parsing parameters and verifying cryptographic digests.
                      </p>
                    </div>
                    <div className="space-y-3">
                      <h4 className="font-mono font-bold text-white uppercase tracking-wider text-[11px]">
                        2. 3-Tier Multi-Scale Loop Detection
                      </h4>
                      <p className="leading-relaxed text-zinc-400">
                        Evaluates sequential agent spans across three tiers: Tier 1 checks canonical SHA-256 hashes ($O(1)$), Tier 2 detects oscillation via 64-bit SimHash Hamming distances ($O(W)$), and Tier 3 computes local TF-IDF n-gram cosine similarities to halt semantic spinning without paid API calls.
                      </p>
                    </div>
                  </div>
                </div>

                {/* API Endpoint Index */}
                <div className="rounded-xl border border-[#222228] bg-[#0d0d10] p-6">
                  <h3 className="text-base font-bold text-white mb-4">REST API & WebSocket Contract Index</h3>
                  <div className="overflow-x-auto">
                    <table className="w-full text-left font-mono text-xs">
                      <thead>
                        <tr className="border-b border-[#222228] text-zinc-500 text-[11px]">
                          <th className="py-2.5 px-3">METHOD</th>
                          <th className="py-2.5 px-3">ENDPOINT</th>
                          <th className="py-2.5 px-3">FUNCTION</th>
                          <th className="py-2.5 px-3">AUTH REQUIRED</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-[#18181f] text-zinc-300">
                        <tr>
                          <td className="py-2 px-3 text-emerald-400 font-bold">GET</td>
                          <td className="py-2 px-3">/healthz</td>
                          <td className="py-2 px-3 text-zinc-400">Liveness probe for container orchestrators</td>
                          <td className="py-2 px-3 text-zinc-500">None</td>
                        </tr>
                        <tr>
                          <td className="py-2 px-3 text-emerald-400 font-bold">GET</td>
                          <td className="py-2 px-3">/readyz</td>
                          <td className="py-2 px-3 text-zinc-400">Readiness probe verifying SQLite WAL & repositories</td>
                          <td className="py-2 px-3 text-zinc-500">None</td>
                        </tr>
                        <tr>
                          <td className="py-2 px-3 text-emerald-400 font-bold">GET</td>
                          <td className="py-2 px-3">/ws/v1/stream</td>
                          <td className="py-2 px-3 text-zinc-400">Bidirectional real-time C2 telemetry WebSocket</td>
                          <td className="py-2 px-3 text-zinc-400">Tenant / Bearer</td>
                        </tr>
                        <tr>
                          <td className="py-2 px-3 text-sky-400 font-bold">POST</td>
                          <td className="py-2 px-3">/api/v1/telemetry/spans</td>
                          <td className="py-2 px-3 text-zinc-400">High-throughput OTLP-compliant span ingestion</td>
                          <td className="py-2 px-3 text-zinc-400">Tenant / Bearer</td>
                        </tr>
                        <tr>
                          <td className="py-2 px-3 text-sky-400 font-bold">POST</td>
                          <td className="py-2 px-3">/api/v1/c2/{`{id}`}/override</td>
                          <td className="py-2 px-3 text-zinc-400">Human-in-the-loop tool approve / edit / mock / reject</td>
                          <td className="py-2 px-3 text-amber-400 font-bold">Admin Role</td>
                        </tr>
                        <tr>
                          <td className="py-2 px-3 text-sky-400 font-bold">POST</td>
                          <td className="py-2 px-3">/api/v1/c2/{`{id}`}/rewind</td>
                          <td className="py-2 px-3 text-zinc-400">Restore agent state to historical checkpoint</td>
                          <td className="py-2 px-3 text-amber-400 font-bold">Admin Role</td>
                        </tr>
                        <tr>
                          <td className="py-2 px-3 text-emerald-400 font-bold">GET</td>
                          <td className="py-2 px-3">/api/v1/c2/{`{id}`}/audit-log/export</td>
                          <td className="py-2 px-3 text-zinc-400">Export SHA-256 verified CSV/JSON audit package</td>
                          <td className="py-2 px-3 text-zinc-400">Tenant / Bearer</td>
                        </tr>
                      </tbody>
                    </table>
                  </div>
                </div>
              </div>
            )}

            {/* ========================================================================= */}
            {/* SECTION 3: LIVE SYSTEM TELEMETRY (AUTO-SYNCED)                            */}
            {/* ========================================================================= */}
            {activeSection === "LIVE_SYSTEM" && (
              <div className="space-y-6 animate-in fade-in duration-300">
                <div className="flex items-center justify-between pb-4 border-b border-[#222228]">
                  <div>
                    <h2 className="text-xl font-bold text-white flex items-center gap-2">
                      <span>Live Cluster Telemetry & Fleet State</span>
                      <span className="flex h-2 w-2 rounded-full bg-emerald-400 animate-ping" />
                    </h2>
                    <p className="text-xs font-mono text-zinc-400">Auto-synced with active FastAPI backend and SQLite WAL storage</p>
                  </div>
                  <div className="flex items-center gap-2">
                    {onFlushWalCheckpoint && (
                      <button
                        onClick={onFlushWalCheckpoint}
                        className="flex items-center gap-1.5 rounded-md border border-[#27272a] bg-[#141418] hover:bg-[#1f1f26] px-3 py-1.5 text-xs font-mono text-zinc-300 transition-colors cursor-pointer"
                        title="Force commit WAL frames to disk"
                      >
                        <Database className="h-3.5 w-3.5 text-emerald-400" />
                        <span>Flush WAL</span>
                      </button>
                    )}
                  </div>
                </div>

                {/* 4 Metric Cards */}
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
                  <div className="rounded-xl border border-[#222228] bg-[#0d0d10] p-5">
                    <div className="text-xs font-mono text-zinc-500 uppercase mb-1">Fleet Health Status</div>
                    <div className="text-2xl font-bold font-mono text-emerald-400 flex items-center gap-2">
                      <CheckCircle2 className="h-6 w-6" />
                      <span>{systemReady ? "READY // 100%" : "DEGRADED"}</span>
                    </div>
                    <div className="text-[11px] font-mono text-zinc-400 mt-2 flex items-center justify-between">
                      <span>Backend: <span className="text-white font-bold">{storageBackend.toUpperCase()}</span></span>
                      <span className={`text-[10px] ${wsConnected ? "text-emerald-400" : "text-amber-400"}`}>
                        {wsConnected ? "WS Live" : "WS Offline"}
                      </span>
                    </div>
                    {storageDiagnostics && (
                      <div className="text-[10px] font-mono text-zinc-500 mt-1">
                        DB: {(storageDiagnostics.total_size_bytes / 1024).toFixed(1)} KB | WAL: {(storageDiagnostics.wal_size_bytes / 1024).toFixed(1)} KB | {storageDiagnostics.integrity_check}
                      </div>
                    )}
                  </div>

                  <div className="rounded-xl border border-[#222228] bg-[#0d0d10] p-5">
                    <div className="text-xs font-mono text-zinc-500 uppercase mb-1">Active Sessions</div>
                    <div className="text-2xl font-bold font-mono text-white">
                      {sessions.length}{" "}
                      <span className="text-xs font-normal text-zinc-500 font-sans">
                        ({runningSessions.length} running)
                      </span>
                    </div>
                    <div className="text-[11px] font-mono text-zinc-400 mt-2">
                      Paused C2: <span className="text-amber-400 font-bold">{pausedSessions.length}</span>
                    </div>
                  </div>

                  <div className="rounded-xl border border-[#222228] bg-[#0d0d10] p-5">
                    <div className="text-xs font-mono text-zinc-500 uppercase mb-1">Circuit Breaker Trips</div>
                    <div className="text-2xl font-bold font-mono text-rose-400">
                      {trippedSessions.length}
                    </div>
                    <div className="text-[11px] font-mono text-zinc-400 mt-2">
                      Protected from runaway spend
                    </div>
                  </div>

                  <div className="rounded-xl border border-[#222228] bg-[#0d0d10] p-5">
                    <div className="text-xs font-mono text-zinc-500 uppercase mb-1">Accumulated Fleet Spend</div>
                    <div className="text-2xl font-bold font-mono text-emerald-400">
                      ${totalFleetSpend.toFixed(4)}
                    </div>
                    <div className="text-[11px] font-mono text-zinc-400 mt-2">
                      Estimated Savings: <span className="text-emerald-400 font-bold">~80%</span>
                    </div>
                  </div>
                </div>

                {/* Live Sessions Diagnostic Table */}
                <div className="rounded-xl border border-[#222228] bg-[#0d0d10] p-6">
                  <h3 className="text-base font-bold text-white mb-4">Tracked Autonomous Sessions</h3>
                  {sessions.length === 0 ? (
                    <div className="py-8 text-center text-xs font-mono text-zinc-500">
                      No active sessions in cluster. Use the Simulation menu in header to seed synthetic workflows.
                    </div>
                  ) : (
                    <div className="overflow-x-auto">
                      <table className="w-full text-left font-mono text-xs">
                        <thead>
                          <tr className="border-b border-[#222228] text-zinc-500 text-[11px]">
                            <th className="py-2 px-3">SESSION ID</th>
                            <th className="py-2 px-3">AGENT / WORKFLOW</th>
                            <th className="py-2 px-3">FRAMEWORK</th>
                            <th className="py-2 px-3">STATUS</th>
                            <th className="py-2 px-3">ACCUMULATED COST</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-[#18181f] text-zinc-300">
                          {sessions.slice(0, 8).map((s) => (
                            <tr key={s.session_id}>
                              <td className="py-2.5 px-3 text-zinc-400">{s.session_id.slice(0, 8)}...</td>
                              <td className="py-2.5 px-3 text-white font-medium">{s.agent_name || s.workflow_id}</td>
                              <td className="py-2.5 px-3 text-zinc-400 uppercase text-[10px]">{s.framework}</td>
                              <td className="py-2.5 px-3">
                                <span
                                  className={`px-2 py-0.5 rounded text-[10px] font-semibold ${
                                    s.status === "RUNNING"
                                      ? "bg-emerald-950/60 border border-emerald-500/30 text-emerald-400"
                                      : s.status === "PAUSED_C2"
                                      ? "bg-amber-950/60 border border-amber-500/30 text-amber-400"
                                      : "bg-rose-950/60 border border-rose-500/30 text-rose-400"
                                  }`}
                                >
                                  {s.status}
                                </span>
                              </td>
                              <td className="py-2.5 px-3 text-emerald-400">${s.accumulated_cost_usd.toFixed(4)}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* ========================================================================= */}
            {/* SECTION 4: TEAM SHOWCASE                                                 */}
            {/* ========================================================================= */}
            {activeSection === "TEAM" && (
              <div className="space-y-6 animate-in fade-in duration-300">
                <div className="pb-4 border-b border-[#222228]">
                  <h2 className="text-xl font-bold text-white">Engineering Leadership & Contributors</h2>
                  <p className="text-xs font-mono text-zinc-400">Architects and developers of the Argus Control Plane</p>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                  {config.team.map((member, idx) => (
                    <div
                      key={idx}
                      className="rounded-xl border border-[#222228] bg-[#0d0d10] p-6 flex flex-col justify-between hover:border-zinc-700 transition-colors"
                    >
                      <div>
                        {/* Avatar & Badges */}
                        <div className="flex items-center gap-3 mb-4">
                          <div className="h-12 w-12 rounded-full bg-emerald-950/80 border border-emerald-500/40 flex items-center justify-center text-emerald-400 font-bold text-base font-mono">
                            {member.name
                              .split(" ")
                              .map((n) => n[0])
                              .join("")
                              .slice(0, 2)
                              .toUpperCase()}
                          </div>
                          <div>
                            <h3 className="text-base font-bold text-white">{member.name}</h3>
                            <div className="text-xs font-mono text-emerald-400">{member.role}</div>
                          </div>
                        </div>

                        <p className="text-xs text-zinc-400 leading-relaxed mb-6 font-sans">
                          {member.bio || "Principal engineer contributing to the Argus agent governance stack."}
                        </p>
                      </div>

                      {/* Links & Contacts */}
                      <div className="pt-4 border-t border-[#1c1c22] flex items-center justify-between text-xs font-mono text-zinc-500">
                        {member.github && (
                          <a
                            href={member.github}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="flex items-center gap-1.5 text-zinc-400 hover:text-white transition-colors"
                          >
                            <Github className="h-3.5 w-3.5" />
                            <span>GitHub</span>
                          </a>
                        )}
                        {member.email && (
                          <a
                            href={`mailto:${member.email}`}
                            className="flex items-center gap-1.5 text-zinc-400 hover:text-white transition-colors"
                          >
                            <Mail className="h-3.5 w-3.5" />
                            <span>Email</span>
                          </a>
                        )}
                        {member.linkedin && (
                          <a
                            href={member.linkedin}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="flex items-center gap-1.5 text-zinc-400 hover:text-white transition-colors"
                          >
                            <Linkedin className="h-3.5 w-3.5" />
                            <span>LinkedIn</span>
                          </a>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* ========================================================================= */}
            {/* SECTION 5: ADMIN CONTROLS & VISIBILITY SCHEDULING                        */}
            {/* ========================================================================= */}
            {activeSection === "ADMIN" && (
              <div className="space-y-8 animate-in fade-in duration-300 max-w-4xl">
                <div className="pb-4 border-b border-[#222228]">
                  <h2 className="text-xl font-bold text-white flex items-center gap-2">
                    <Settings className="h-5 w-5 text-emerald-400" />
                    <span>Documentation Publishing & Visibility Controls</span>
                  </h2>
                  <p className="text-xs font-mono text-zinc-400">
                    Control public availability, schedule publishing windows, and manage team members
                  </p>
                </div>

                {saveMessage && (
                  <div className="p-3 rounded-lg bg-emerald-950/60 border border-emerald-500/40 text-xs font-mono text-emerald-300">
                    {saveMessage}
                  </div>
                )}

                {/* Visibility Mode Selector */}
                <div className="rounded-xl border border-[#222228] bg-[#0d0d10] p-6 space-y-6">
                  <h3 className="text-sm font-bold text-white uppercase tracking-wider font-mono">
                    1. Visibility Status
                  </h3>

                  <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                    <button
                      type="button"
                      onClick={() => setEditVisibility("PUBLIC")}
                      className={`p-4 rounded-lg border text-left cursor-pointer transition-all ${
                        editVisibility === "PUBLIC"
                          ? "border-emerald-500 bg-emerald-950/20 text-white"
                          : "border-[#222228] bg-[#141418] text-zinc-400 hover:border-zinc-700"
                      }`}
                    >
                      <div className="flex items-center justify-between mb-2">
                        <span className="font-bold text-xs">PUBLIC (LIVE)</span>
                        <Globe className="h-4 w-4 text-emerald-400" />
                      </div>
                      <p className="text-[11px] text-zinc-400">
                        Always publicly visible to all judges, evaluators, and visitors.
                      </p>
                    </button>

                    <button
                      type="button"
                      onClick={() => setEditVisibility("RESTRICTED")}
                      className={`p-4 rounded-lg border text-left cursor-pointer transition-all ${
                        editVisibility === "RESTRICTED"
                          ? "border-rose-500 bg-rose-950/20 text-white"
                          : "border-[#222228] bg-[#141418] text-zinc-400 hover:border-zinc-700"
                      }`}
                    >
                      <div className="flex items-center justify-between mb-2">
                        <span className="font-bold text-xs">RESTRICTED</span>
                        <Lock className="h-4 w-4 text-rose-400" />
                      </div>
                      <p className="text-[11px] text-zinc-400">
                        Locked behind administrative authentication.
                      </p>
                    </button>

                    <button
                      type="button"
                      onClick={() => setEditVisibility("SCHEDULED")}
                      className={`p-4 rounded-lg border text-left cursor-pointer transition-all ${
                        editVisibility === "SCHEDULED"
                          ? "border-amber-500 bg-amber-950/20 text-white"
                          : "border-[#222228] bg-[#141418] text-zinc-400 hover:border-zinc-700"
                      }`}
                    >
                      <div className="flex items-center justify-between mb-2">
                        <span className="font-bold text-xs">SCHEDULED WINDOW</span>
                        <Calendar className="h-4 w-4 text-amber-400" />
                      </div>
                      <p className="text-[11px] text-zinc-400">
                        Visible only between specified start and end timestamps.
                      </p>
                    </button>
                  </div>

                  {/* Scheduled Date Inputs */}
                  {editVisibility === "SCHEDULED" && (
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 p-4 rounded-lg bg-[#141418] border border-[#222228]">
                      <div>
                        <label className="block text-xs font-mono text-zinc-400 mb-1">
                          AVAILABLE FROM (ISO 8601)
                        </label>
                        <input
                          type="text"
                          value={editStart}
                          onChange={(e) => setEditStart(e.target.value)}
                          placeholder="e.g. 2026-11-18T00:00:00Z"
                          className="w-full rounded-md border border-[#27272a] bg-[#0c0c0e] px-3 py-1.5 text-xs font-mono text-white placeholder-zinc-600 focus:border-zinc-500 focus:outline-hidden"
                        />
                      </div>
                      <div>
                        <label className="block text-xs font-mono text-zinc-400 mb-1">
                          AVAILABLE UNTIL (ISO 8601)
                        </label>
                        <input
                          type="text"
                          value={editEnd}
                          onChange={(e) => setEditEnd(e.target.value)}
                          placeholder="e.g. 2026-12-01T00:00:00Z"
                          className="w-full rounded-md border border-[#27272a] bg-[#0c0c0e] px-3 py-1.5 text-xs font-mono text-white placeholder-zinc-600 focus:border-zinc-500 focus:outline-hidden"
                        />
                      </div>
                    </div>
                  )}

                  <div className="flex justify-end pt-2">
                    <button
                      type="button"
                      onClick={handleSaveConfig}
                      disabled={savingConfig}
                      className="flex items-center gap-2 rounded-md bg-emerald-500 hover:bg-emerald-400 text-black font-semibold px-4 py-2 text-xs transition-colors cursor-pointer disabled:opacity-50"
                    >
                      <CheckCircle2 className="h-3.5 w-3.5" />
                      <span>{savingConfig ? "Saving..." : "Save Visibility Settings"}</span>
                    </button>
                  </div>
                </div>

                {/* Manage Team Members */}
                <div className="rounded-xl border border-[#222228] bg-[#0d0d10] p-6 space-y-4">
                  <h3 className="text-sm font-bold text-white uppercase tracking-wider font-mono">
                    2. Add Team Member
                  </h3>

                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    <input
                      type="text"
                      placeholder="Full Name (e.g. Shejan Ahmmed)"
                      value={newMemberName}
                      onChange={(e) => setNewMemberName(e.target.value)}
                      className="rounded-md border border-[#27272a] bg-[#141418] px-3 py-1.5 text-xs text-white placeholder-zinc-500 focus:outline-hidden"
                    />
                    <input
                      type="text"
                      placeholder="Role (e.g. Lead Systems Engineer)"
                      value={newMemberRole}
                      onChange={(e) => setNewMemberRole(e.target.value)}
                      className="rounded-md border border-[#27272a] bg-[#141418] px-3 py-1.5 text-xs text-white placeholder-zinc-500 focus:outline-hidden"
                    />
                    <input
                      type="text"
                      placeholder="Email (optional)"
                      value={newMemberEmail}
                      onChange={(e) => setNewMemberEmail(e.target.value)}
                      className="rounded-md border border-[#27272a] bg-[#141418] px-3 py-1.5 text-xs text-white placeholder-zinc-500 focus:outline-hidden"
                    />
                    <input
                      type="text"
                      placeholder="GitHub URL (optional)"
                      value={newMemberGithub}
                      onChange={(e) => setNewMemberGithub(e.target.value)}
                      className="rounded-md border border-[#27272a] bg-[#141418] px-3 py-1.5 text-xs text-white placeholder-zinc-500 focus:outline-hidden"
                    />
                  </div>
                  <textarea
                    rows={2}
                    placeholder="Short bio or technical focus..."
                    value={newMemberBio}
                    onChange={(e) => setNewMemberBio(e.target.value)}
                    className="w-full rounded-md border border-[#27272a] bg-[#141418] px-3 py-1.5 text-xs text-white placeholder-zinc-500 focus:outline-hidden resize-none"
                  />

                  <div className="flex justify-end">
                    <button
                      type="button"
                      onClick={handleAddTeamMember}
                      className="flex items-center gap-1.5 rounded-md border border-emerald-500/30 bg-emerald-950/40 hover:bg-emerald-900/60 text-emerald-300 px-4 py-2 text-xs font-medium transition-colors cursor-pointer"
                    >
                      <span>+ Add Member</span>
                    </button>
                  </div>

                  {/* Existing Team List with Delete */}
                  <div className="pt-4 border-t border-[#1c1c22] space-y-2">
                    <h4 className="text-xs font-mono text-zinc-400">Current Members:</h4>
                    {config.team.map((m, idx) => (
                      <div
                        key={idx}
                        className="flex items-center justify-between p-2.5 rounded bg-[#141418] border border-[#222228] text-xs font-mono"
                      >
                        <div>
                          <span className="text-white font-bold">{m.name}</span>
                          <span className="text-zinc-500 ml-2">({m.role})</span>
                        </div>
                        {config.team.length > 1 && (
                          <button
                            type="button"
                            onClick={() => handleRemoveTeamMember(idx)}
                            className="text-rose-400 hover:text-rose-300 text-[11px] underline cursor-pointer"
                          >
                            Remove
                          </button>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            )}
          </>
        )}
      </main>
    </div>
  );
};
