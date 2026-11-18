import React, { useState, useEffect, useRef, useCallback } from "react";
import { ArgusLogo } from "./ArgusLogo";
import { ShieldCheck, Terminal, Cpu } from "lucide-react";

interface BootSplashScreenProps {
  onComplete: () => void;
}

export const BootSplashScreen: React.FC<BootSplashScreenProps> = ({ onComplete }) => {
  const [phase, setPhase] = useState<number>(1); // 1: logo bloom, 2: telemetry diagnostics, 3: fade-out
  const [progress, setProgress] = useState<number>(0);
  const [activeLogs, setActiveLogs] = useState<number>(0);
  const [isDismissing, setIsDismissing] = useState<boolean>(false);

  // Store onComplete in a ref so changes in parent callback reference do NOT invalidate timers
  const onCompleteRef = useRef(onComplete);
  useEffect(() => {
    onCompleteRef.current = onComplete;
  }, [onComplete]);

  // Synchronous guard against multiple dismiss executions
  const isDismissingRef = useRef<boolean>(false);

  // Reference-stable dismiss callback with zero state dependencies
  const dismiss = useCallback(() => {
    if (isDismissingRef.current) return;
    isDismissingRef.current = true;
    setIsDismissing(true);

    try {
      sessionStorage.setItem("argus_boot_shown", "true");
    } catch {
      // Fallback for sandboxed or private browsing quota limits
    }

    setTimeout(() => {
      onCompleteRef.current();
    }, 450);
  }, []);

  // Check reduced motion or previous session boot
  useEffect(() => {
    if (typeof window !== "undefined") {
      const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      if (reducedMotion || sessionStorage.getItem("argus_boot_shown")) {
        onCompleteRef.current();
        return;
      }
    }
  }, []);

  // Keyboard shortcut listener (ESC, Space, Enter)
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape" || e.key === " " || e.key === "Enter") {
        e.preventDefault();
        dismiss();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [dismiss]);

  // Staged animation timing sequence - executes exactly once
  useEffect(() => {
    // Stage 1 to 2 transition: trigger diagnostic lines
    const timerPhase2 = setTimeout(() => {
      setPhase(2);
    }, 600);

    // Progressive ticker logs
    const timerLog1 = setTimeout(() => setActiveLogs(1), 750);
    const timerLog2 = setTimeout(() => setActiveLogs(2), 1050);
    const timerLog3 = setTimeout(() => setActiveLogs(3), 1350);

    // Smooth progress bar increment
    const intervalProgress = setInterval(() => {
      setProgress((prev) => {
        if (prev >= 100) {
          clearInterval(intervalProgress);
          return 100;
        }
        return prev + 4;
      });
    }, 50);

    // Stage 3 transition: begin fade out
    const timerPhase3 = setTimeout(() => {
      setPhase(3);
    }, 1800);

    // Final completion
    const timerComplete = setTimeout(() => {
      dismiss();
    }, 2200);

    return () => {
      clearTimeout(timerPhase2);
      clearTimeout(timerLog1);
      clearTimeout(timerLog2);
      clearTimeout(timerLog3);
      clearInterval(intervalProgress);
      clearTimeout(timerPhase3);
      clearTimeout(timerComplete);
    };
  }, [dismiss]);

  const diagnosticItems = [
    { text: "INITIALIZING INLINE TELEMETRY BUS", icon: Terminal },
    { text: "VERIFYING SHA-256 AUDIT GENESIS LEDGER", icon: ShieldCheck },
    { text: "ENGAGING PRE-EXECUTION MCP CIRCUIT BREAKERS", icon: Cpu },
  ];

  return (
    <div
      onClick={dismiss}
      className={`fixed inset-0 z-50 flex flex-col items-center justify-center bg-[#070709] transition-all duration-500 cursor-pointer select-none ${
        isDismissing || phase === 3
          ? "opacity-0 scale-102 pointer-events-none"
          : "opacity-100 scale-100"
      }`}
      aria-label="Argus System Initialization"
      role="dialog"
    >
      {/* Background Radial Glow */}
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,rgba(16,185,129,0.08)_0%,transparent_70%)] pointer-events-none" />

      {/* Center Boot Console */}
      <div className="relative z-10 flex flex-col items-center max-w-md px-6 text-center">
        {/* Logo with Soft Emerald Bloom */}
        <div className="relative mb-6 flex items-center justify-center">
          <div className="absolute -inset-4 rounded-full bg-emerald-500/10 blur-xl animate-pulse" />
          <ArgusLogo
            className={`relative h-20 w-20 text-emerald-400 drop-shadow-[0_0_20px_rgba(16,185,129,0.35)] transition-all duration-700 ease-out ${
              phase >= 1 ? "scale-100 opacity-100" : "scale-75 opacity-0"
            }`}
          />
        </div>

        {/* Title & Tagline */}
        <div
          className={`transition-all duration-500 ease-out ${
            phase >= 1 ? "translate-y-0 opacity-100" : "translate-y-2 opacity-0"
          }`}
        >
          <div className="flex items-center justify-center gap-2 mb-1">
            <h1 className="text-2xl font-bold tracking-widest text-white font-sans uppercase">
              Argus
            </h1>
            <span className="rounded bg-emerald-950/60 border border-emerald-500/30 px-1.5 py-0.5 text-[10px] font-mono font-semibold text-emerald-400 tracking-wider">
              C2
            </span>
          </div>
          <p className="text-[11px] font-mono text-zinc-400 tracking-wider uppercase mb-6">
            Autonomous Agent Governance Plane
          </p>
        </div>

        {/* High-Speed Diagnostic Ticker */}
        <div className="w-full max-w-xs flex flex-col gap-1.5 mb-6 text-left min-h-[72px]">
          {diagnosticItems.map((item, idx) => {
            const isVisible = activeLogs > idx;
            const IconComponent = item.icon;
            return (
              <div
                key={idx}
                className={`flex items-center justify-between text-[10px] font-mono transition-all duration-300 ${
                  isVisible ? "opacity-100 translate-x-0" : "opacity-0 -translate-x-2"
                }`}
              >
                <span className="flex items-center gap-1.5 text-zinc-400">
                  <IconComponent className="h-3 w-3 text-emerald-400 shrink-0" />
                  <span>{item.text}</span>
                </span>
                <span className="text-emerald-400 font-semibold shrink-0 ml-2">[OK]</span>
              </div>
            );
          })}
        </div>

        {/* Progress Track */}
        <div className="w-full max-w-xs mb-4">
          <div className="h-1 w-full bg-[#16161c] rounded-full overflow-hidden border border-[#22222a]">
            <div
              className="h-full bg-emerald-400 transition-all duration-75 ease-out shadow-[0_0_8px_rgba(52,211,153,0.6)]"
              style={{ width: `${progress}%` }}
            />
          </div>
          <div className="flex justify-between items-center text-[9px] font-mono text-zinc-500 mt-1">
            <span>SYS_INIT</span>
            <span>{progress}%</span>
          </div>
        </div>

        {/* Dismiss hint */}
        <p className="text-[10px] font-mono text-zinc-600 tracking-wide animate-pulse">
          Click anywhere or press [ESC] to enter
        </p>
      </div>
    </div>
  );
};
