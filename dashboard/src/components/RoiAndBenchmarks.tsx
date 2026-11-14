import React from "react";
import { TrendingUp, Zap, ArrowDownRight } from "lucide-react";
import { WorkflowROIAttribution, ModelBenchmarkEntry, DowngradeRecommendation } from "../types";

interface RoiAndBenchmarksProps {
  roi: WorkflowROIAttribution | null;
  benchmarks: ModelBenchmarkEntry[];
  recommendations: DowngradeRecommendation[];
}

export const RoiAndBenchmarks: React.FC<RoiAndBenchmarksProps> = ({
  roi,
  benchmarks,
  recommendations,
}) => {
  return (
    <div className="terminal-card flex flex-col h-full font-mono text-xs">
      <div className="dot-matrix-header flex items-center justify-between px-4 py-2">
        <span className="text-[#00ff66]">[ 04 // FINANCIAL ROI ATTRIBUTION & HF PARETO MATRIX ]</span>
        <span className="text-[#666666]">ZERO-SPEND BUDGET ANALYSIS</span>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-3 p-3 flex-1">
        {/* Left: ROI Attribution Breakdown */}
        <div className="flex flex-col border border-[#222222] bg-[#030303] p-3">
          <div className="flex items-center space-x-1.5 text-white font-bold mb-3">
            <TrendingUp className="h-4 w-4 text-[#00ff66]" />
            <span>SESSION FINANCIAL ATTRIBUTION</span>
          </div>

          {roi ? (
            <div className="space-y-2.5 flex-1 flex flex-col justify-between">
              <div className="grid grid-cols-2 gap-2 text-[11px]">
                <div className="border border-[#1a1a1a] p-2 bg-[#050505]">
                  <div className="text-[#777777]">ASSIGNED VALUE:</div>
                  <div className="text-white font-bold text-sm">
                    ${roi.assigned_business_value_usd.toFixed(2)}
                  </div>
                </div>
                <div className="border border-[#1a1a1a] p-2 bg-[#050505]">
                  <div className="text-[#777777]">TOTAL INFERENCE COST:</div>
                  <div className="text-[#00ff66] font-bold text-sm">
                    ${roi.total_cost_usd.toFixed(4)}
                  </div>
                </div>
                <div className="border border-[#1a1a1a] p-2 bg-[#050505]">
                  <div className="text-[#777777]">NET ROI:</div>
                  <div className={`font-bold text-sm ${roi.net_roi_usd >= 0 ? "text-[#00ff66]" : "text-[#ff3333]"}`}>
                    ${roi.net_roi_usd.toFixed(2)}
                  </div>
                </div>
                <div className="border border-[#1a1a1a] p-2 bg-[#050505]">
                  <div className="text-[#777777]">WASTED LOOP COST:</div>
                  <div className={`font-bold text-sm ${roi.wasted_loop_cost_usd > 0 ? "text-[#ff3333]" : "text-white"}`}>
                    ${roi.wasted_loop_cost_usd.toFixed(4)}
                  </div>
                </div>
              </div>

              <div className="border-t border-[#222222] pt-2 text-[10px] space-y-1 text-[#888888]">
                <div className="flex justify-between">
                  <span>LLM TOKENS:</span>
                  <span className="text-white">${roi.llm_cost_usd.toFixed(4)}</span>
                </div>
                <div className="flex justify-between">
                  <span>TOOL INVOCATIONS:</span>
                  <span className="text-white">${roi.tool_cost_usd.toFixed(4)}</span>
                </div>
                <div className="flex justify-between">
                  <span>INFRASTRUCTURE:</span>
                  <span className="text-white">${roi.infra_cost_usd.toFixed(4)}</span>
                </div>
                <div className="flex justify-between">
                  <span>C2 HUMAN OVERHEAD:</span>
                  <span className="text-white">${roi.c2_intervention_cost_usd.toFixed(4)}</span>
                </div>
              </div>
            </div>
          ) : (
            <div className="flex-1 flex items-center justify-center text-[#555555]">
              SELECT A SESSION TO CALCULATE ATTRIBUTION
            </div>
          )}
        </div>

        {/* Right: Hugging Face Open-Weight Pareto Recommendations */}
        <div className="flex flex-col border border-[#222222] bg-[#030303] p-3">
          <div className="flex items-center justify-between text-white font-bold mb-3">
            <span className="flex items-center space-x-1.5">
              <Zap className="h-4 w-4 text-[#00e5ff]" />
              <span>HF MODEL PARETO FRONTIER</span>
            </span>
            <span className="text-[10px] text-[#00e5ff] font-normal">EFFICIENCY ENGINE</span>
          </div>

          <div className="flex-1 flex flex-col space-y-2 overflow-y-auto max-h-[220px]">
            {recommendations.length > 0 ? (
              recommendations.map((rec, i) => (
                <div
                  key={i}
                  className="border border-[#222222] hover:border-[#00e5ff] p-2 bg-[#060606] transition-colors"
                >
                  <div className="flex items-center justify-between text-[11px] font-bold">
                    <span className="text-white">{rec.candidate_model}</span>
                    <span className="text-[#00ff66] flex items-center">
                      <ArrowDownRight className="h-3 w-3 mr-0.5" />
                      -{rec.cost_savings_pct}% COST
                    </span>
                  </div>
                  <div className="flex justify-between text-[10px] text-[#888888] mt-1">
                    <span>PROVIDER: {rec.provider}</span>
                    <span>LATENCY: -{rec.latency_reduction_pct}%</span>
                    <span>ACCURACY DELTA: {rec.benchmark_accuracy_delta}</span>
                  </div>
                </div>
              ))
            ) : (
              <div className="space-y-1.5">
                {benchmarks.slice(0, 4).map((m, i) => (
                  <div key={i} className="flex justify-between border-b border-[#181818] pb-1 text-[11px]">
                    <span className="text-white font-bold">{m.model_name}</span>
                    <span className="text-[#888888]">
                      GAIA: {(m.gaia_accuracy * 100).toFixed(0)}% • ${m.input_cost_per_1k}/1K
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
