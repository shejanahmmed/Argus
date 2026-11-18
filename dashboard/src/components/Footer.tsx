import React, { useState } from "react";
import {
  Database,
  Download,
  CheckCircle2,
  Sparkles,
  Scale,
  ExternalLink,
  X,
  FileText,
} from "lucide-react";
import { ArgusLogo } from "./ArgusLogo";
import { AgentSession, StorageDiagnostics, ViewMode } from "../types";

export interface FooterProps {
  wsConnected: boolean;
  sessions: AgentSession[];
  selectedSessionId: string | null;
  tenantId: string;
  workspaceId: string;
  storageBackend?: string;
  storageDiagnostics?: StorageDiagnostics | null;
  systemReady?: boolean;
  onExportAuditLog?: (sessionId: string) => void;
  onSelectView?: (view: ViewMode) => void;
}

export const Footer: React.FC<FooterProps> = ({
  wsConnected,
  sessions,
  selectedSessionId,
  storageBackend = "sqlite",
  storageDiagnostics,
  systemReady = true,
  onExportAuditLog,
  onSelectView,
}) => {
  const [showLicenseModal, setShowLicenseModal] = useState<boolean>(false);

  const activeCount = sessions.filter((s) => s.status === "RUNNING").length;
  const pausedCount = sessions.filter((s) => s.status === "PAUSED_C2").length;
  const trippedCount = sessions.filter(
    (s) => s.status === "TRIPPED_LOOP" || s.status === "TRIPPED_BUDGET"
  ).length;
  const totalCost = sessions.reduce((acc, s) => acc + s.accumulated_cost_usd, 0);

  const handleExportClick = () => {
    if (!selectedSessionId) return;
    if (onExportAuditLog) {
      onExportAuditLog(selectedSessionId);
    } else {
      window.open(`/api/v1/c2/${selectedSessionId}/audit-log/export?format=json`, "_blank");
    }
  };

  return (
    <>
      <footer className="border-t border-[#18181c] bg-[#070709] px-4 h-9 font-mono text-[11px] text-zinc-400 select-none flex items-center shrink-0">
        <div className="w-full flex items-center justify-between gap-4 overflow-hidden whitespace-nowrap">
          {/* Left: Brand & Engine Telemetry */}
          <div className="flex items-center gap-2.5 shrink-0 whitespace-nowrap">
            <div className="flex items-center gap-1.5 text-zinc-200">
              <ArgusLogo className="h-3.5 w-3.5 text-emerald-400 shrink-0" />
              <span className="font-sans font-bold tracking-wider text-xs uppercase text-white">
                Argus C2
              </span>
            </div>

            <span className="text-zinc-700">·</span>

            {/* Live Stream Status Indicator */}
            <div
              className="flex items-center gap-1.5"
              title={
                wsConnected
                  ? "WebSocket real-time telemetry stream active"
                  : "Reconnecting to event stream (/ws/v1/stream)..."
              }
            >
              <span className="relative flex h-2 w-2 shrink-0">
                {wsConnected && (
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
                )}
                <span
                  className={`relative inline-flex rounded-full h-2 w-2 ${
                    wsConnected ? "bg-emerald-400" : "bg-amber-400"
                  }`}
                />
              </span>
              <span className={wsConnected ? "text-emerald-400 font-medium" : "text-amber-400"}>
                {wsConnected ? "Stream Live" : "Reconnecting"}
              </span>
            </div>

            <span className="text-zinc-700 hidden sm:inline">·</span>

            {/* Storage Engine Status */}
            <div
              className="hidden sm:flex items-center gap-1 text-zinc-400"
              title={
                storageDiagnostics
                  ? `DB Path: ${storageDiagnostics.db_path} | Journal: ${storageDiagnostics.journal_mode} | Size: ${(
                      storageDiagnostics.total_size_bytes / 1024
                    ).toFixed(1)} KB`
                  : `Storage Engine: ${storageBackend.toUpperCase()}`
              }
            >
              <Database className="h-3 w-3 text-zinc-500 shrink-0" />
              <span>
                {storageBackend.toUpperCase()}
                <span className="text-zinc-600 ml-1">
                  ({storageDiagnostics?.journal_mode?.toUpperCase() || "WAL"})
                </span>
              </span>
            </div>

            <span className="text-zinc-700 hidden md:inline">·</span>

            {/* Health State */}
            <div className="hidden md:flex items-center gap-1 text-zinc-400">
              <CheckCircle2
                className={`h-3 w-3 ${systemReady ? "text-emerald-400" : "text-rose-400"} shrink-0`}
              />
              <span className={systemReady ? "text-zinc-300" : "text-rose-400"}>
                {systemReady ? "Ready" : "Degraded"}
              </span>
            </div>
          </div>

          {/* Center: Live Fleet Metrics Rollup */}
          <div className="hidden lg:flex items-center gap-2 text-zinc-400 text-[11px] shrink-0 whitespace-nowrap">
            <span className="text-zinc-500 text-[10px] tracking-wider uppercase">Fleet:</span>
            <span className="flex items-center gap-1 text-emerald-400">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 shrink-0" />
              {activeCount}&nbsp;active
            </span>
            <span className="text-zinc-700">·</span>
            <span className="flex items-center gap-1 text-amber-400">
              <span className="h-1.5 w-1.5 rounded-full bg-amber-400 shrink-0" />
              {pausedCount}&nbsp;paused
            </span>
            {trippedCount > 0 && (
              <>
                <span className="text-zinc-700">·</span>
                <span className="flex items-center gap-1 text-rose-400">
                  <span className="h-1.5 w-1.5 rounded-full bg-rose-400 shrink-0" />
                  {trippedCount}&nbsp;tripped
                </span>
              </>
            )}
            <span className="text-zinc-700">·</span>
            <span className="text-zinc-200 font-semibold">${totalCost.toFixed(4)}</span>
          </div>

          {/* Right: Docs Deck, API Specs, and Interactive Apache-2.0 License */}
          <div className="flex items-center gap-2.5 text-zinc-400 shrink-0 whitespace-nowrap">
            {/* Featured /docs Pitch Deck Button */}
            {onSelectView && (
              <button
                onClick={() => onSelectView("DOCS")}
                className="flex items-center gap-1.5 px-2 py-0.5 rounded bg-emerald-950/40 hover:bg-emerald-900/60 border border-emerald-500/30 text-emerald-300 hover:text-white text-[10px] font-mono transition-all cursor-pointer"
                title="Open Live /docs Pitch Deck, Technical Whitepaper & Cluster Telemetry"
              >
                <Sparkles className="h-3 w-3 text-emerald-400 shrink-0" />
                <span>/docs Pitch Deck</span>
              </button>
            )}

            {/* Subtle API Docs Link */}
            <a
              href="/api/docs"
              target="_blank"
              rel="noreferrer"
              className="hidden sm:inline hover:text-zinc-200 transition-colors"
              title="Interactive OpenAPI 3.1 Swagger Specification"
            >
              API Specs
            </a>

            {/* Export Audit Log Button (Conditional) */}
            {selectedSessionId && (
              <button
                onClick={handleExportClick}
                className="flex items-center gap-1 px-1.5 py-0.5 rounded bg-[#16161b] hover:bg-[#202028] border border-[#27272f] text-zinc-300 text-[10px] transition-colors cursor-pointer"
                title={`Export SHA-256 audit ledger for session ${selectedSessionId}`}
              >
                <Download className="h-2.5 w-2.5 text-emerald-400 shrink-0" />
                <span>Audit</span>
              </button>
            )}

            <span className="text-zinc-700">·</span>

            {/* Interactive Apache 2.0 License & Copyright */}
            <button
              onClick={() => setShowLicenseModal(true)}
              className="flex items-center gap-1 text-emerald-400 hover:text-emerald-300 hover:underline cursor-pointer transition-colors"
              title="Click to view full Apache-2.0 open-source license and copyright terms"
            >
              <Scale className="h-3 w-3 text-emerald-400 shrink-0" />
              <span className="font-semibold">Apache-2.0</span>
            </button>
            <span className="text-zinc-600 hidden sm:inline">·</span>
            <span className="text-zinc-500 font-sans text-[11px] hidden sm:inline">
              © 2026 Argus Contributors
            </span>
          </div>
        </div>
      </footer>

      {/* Official Apache 2.0 License Modal */}
      {showLicenseModal && (
        <div
          onClick={(e) => {
            if (e.target === e.currentTarget) setShowLicenseModal(false);
          }}
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-xs p-4 animate-in fade-in duration-200"
          role="dialog"
          aria-modal="true"
        >
          <div className="w-full max-w-lg rounded-xl border border-[#27272a] bg-[#0c0c0e] p-6 shadow-2xl font-mono text-zinc-200">
            {/* Header */}
            <div className="flex items-center justify-between pb-4 border-b border-[#222228]">
              <div className="flex items-center gap-2.5">
                <div className="p-1.5 rounded-md bg-emerald-950/60 border border-emerald-500/40 text-emerald-400">
                  <Scale className="h-4 w-4" />
                </div>
                <div>
                  <h3 className="text-sm font-bold text-white font-sans">
                    Argus Open Source License
                  </h3>
                  <p className="text-[10px] text-zinc-500">
                    Official Apache License, Version 2.0
                  </p>
                </div>
              </div>
              <button
                onClick={() => setShowLicenseModal(false)}
                className="rounded-md p-1 text-zinc-400 hover:text-white hover:bg-zinc-800 transition-colors cursor-pointer"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            {/* License Overview */}
            <div className="py-5 space-y-4 text-xs font-sans">
              <div className="p-3 rounded-lg bg-[#141418] border border-[#222228] font-mono text-[11px] space-y-1">
                <div className="text-emerald-400 font-bold">
                  Copyright 2026 Shejan Ahmmed / Argus Contributors
                </div>
                <div className="text-zinc-400">
                  Licensed under the Apache License, Version 2.0 (the &quot;License&quot;).
                </div>
              </div>

              <div className="space-y-2 text-zinc-300 text-xs leading-relaxed">
                <p>
                  Argus is 100% free and open-source software built for enterprise governance, observability, and Command & Control of autonomous AI agents.
                </p>
                <p className="text-zinc-400 text-[11px]">
                  You may reproduce, distribute, modify, and publicly display this software under the terms of the Apache-2.0 license, subject to the conditions of the license.
                </p>
              </div>

              {/* Permissions & Disclaimers Matrix */}
              <div className="grid grid-cols-2 gap-2 text-[11px] font-mono pt-2">
                <div className="p-2 rounded bg-[#121215] border border-[#1f1f24] space-y-1">
                  <div className="text-zinc-500 uppercase text-[9px]">Permissions</div>
                  <div className="text-emerald-400 flex items-center gap-1">✓ Commercial Use</div>
                  <div className="text-emerald-400 flex items-center gap-1">✓ Modification</div>
                  <div className="text-emerald-400 flex items-center gap-1">✓ Distribution</div>
                  <div className="text-emerald-400 flex items-center gap-1">✓ Patent Grants</div>
                </div>
                <div className="p-2 rounded bg-[#121215] border border-[#1f1f24] space-y-1">
                  <div className="text-zinc-500 uppercase text-[9px]">Limitations</div>
                  <div className="text-amber-400 flex items-center gap-1">⚠ No Warranty (AS-IS)</div>
                  <div className="text-amber-400 flex items-center gap-1">⚠ No Trademark Grant</div>
                  <div className="text-zinc-400 flex items-center gap-1">ⓘ License Notice Req.</div>
                  <div className="text-zinc-400 flex items-center gap-1">ⓘ State Changes Req.</div>
                </div>
              </div>
            </div>

            {/* Actions & Links */}
            <div className="flex items-center justify-between pt-4 border-t border-[#222228] text-xs font-mono">
              <a
                href="/LICENSE"
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center gap-1.5 text-emerald-400 hover:text-emerald-300 hover:underline"
              >
                <FileText className="h-3.5 w-3.5" />
                <span>View Full /LICENSE</span>
                <ExternalLink className="h-3 w-3 text-zinc-500" />
              </a>

              <div className="flex items-center gap-2">
                <a
                  href="https://www.apache.org/licenses/LICENSE-2.0"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="rounded-md border border-[#27272a] bg-[#141418] hover:bg-[#1a1a20] px-3 py-1.5 text-zinc-300 transition-colors"
                >
                  Official Apache Spec
                </a>
                <button
                  type="button"
                  onClick={() => setShowLicenseModal(false)}
                  className="rounded-md bg-zinc-800 hover:bg-zinc-700 text-white px-3 py-1.5 transition-colors cursor-pointer"
                >
                  Close
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  );
};
