import React from "react";
import { TrendingUp, Zap, ArrowDownRight, Award, BarChart3 } from "lucide-react";
import {
  WorkflowROIAttribution,
  ModelBenchmarkEntry,
  DowngradeRecommendation,
} from "../types";

interface RoiAndBenchmarksProps {
  roi: WorkflowROIAttribution | null;
  benchmarks: ModelBenchmarkEntry[];
  recommendations: DowngradeRecommendation[];
  businessValueUsd: number;
  onChangeBusinessValue: (val: number) => void;
}

const VALUE_PRESETS = [50, 100, 250, 1000];

export const RoiAndBenchmarks: React.FC<RoiAndBenchmarksProps> = ({
  roi,
  benchmarks,
  recommendations,
  businessValueUsd,
  onChangeBusinessValue,
}) => {
  return (
    <div className="terminal-card flex flex-col font-mono text-xs">
      <div className="dot-matrix-header flex flex-wrap items-center justify-between gap-3 px-4 py-3">
        <div className="flex items-center gap-2">
          <BarChart3 className="h-4 w-4 text-[#00ff66]" />
          <span className="text-[#00ff66]">
            [ 04 // FINANCIAL ROI ATTRIBUTION & HUGGING FACE PARETO MATRIX ]
          </span>
        </div>

        <div className="flex items-center gap-1.5 text-[10px]">
          <span className="text-[#737373] mr-1">TASK VALUE USD:</span>
          {VALUE_PRESETS.map((val) => (
            <button
              key={val}
              onClick={() => onChangeBusinessValue(val)}
              className={`px-2 py-0.5 border font-bold cursor-pointer transition-colors ${
                businessValueUsd === val
                  ? "border-[#00ff66] bg-[#00ff66] text-black"
                  : "border-[#262626] bg-[#0a0a0a] text-[#888888] hover:text-white"
              }`}
            >
              ${val}
            </button>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4 p-4">
        {/* Left: Financial Attribution & Trajectory Evaluation */}
        <div className="flex flex-col border border-[#222222] bg-[#060606] p-4">
          <div className="flex items-center justify-between pb-3 mb-3 border-b border-[#1a1a1a]">
            <span className="flex items-center gap-2 text-white font-bold">
              <TrendingUp className="h-4 w-4 text-[#00ff66]" />
              <span>WORKFLOW FINANCIAL ATTRIBUTION</span>
            </span>
            {roi && (
              <span
                className={`px-2 py-0.5 text-[10px] font-bold border ${
                  roi.task_completed
                    ? "border-[#00ff66] bg-[#001808] text-[#00ff66]"
                    : "border-[#ffb000] bg-[#1f1300] text-[#ffb000]"
                }`}
              >
                {roi.task_completed ? "GOAL VERIFIED" : "IN PROGRESS / HALTED"}
              </span>
            )}
          </div>

          {roi ? (
            <div className="space-y-3.5 flex-1 flex flex-col justify-between">
              <div className="grid grid-cols-2 gap-2.5 text-[11px]">
                <div className="border border-[#1c1c1c] p-3 bg-[#030303]">
                  <div className="text-[#737373] text-[10px] mb-0.5">ASSIGNED BUSINESS VALUE</div>
                  <div className="text-white font-bold text-base">
                    ${roi.assigned_business_value_usd.toFixed(2)}
                  </div>
                </div>
                <div className="border border-[#1c1c1c] p-3 bg-[#030303]">
                  <div className="text-[#737373] text-[10px] mb-0.5">TOTAL EXECUTION COST</div>
                  <div className="text-[#00e5ff] font-bold text-base">
                    ${roi.total_cost_usd.toFixed(4)}
                  </div>
                </div>
                <div className="border border-[#1c1c1c] p-3 bg-[#030303]">
                  <div className="text-[#737373] text-[10px] mb-0.5">NET WORKFLOW VALUE</div>
                  <div
                    className={`font-bold text-base ${
                      roi.net_roi_usd >= 0 ? "text-[#00ff66]" : "text-[#ff3333]"
                    }`}
                  >
                    ${roi.net_roi_usd.toFixed(2)}
                  </div>
                </div>
                <div className="border border-[#1c1c1c] p-3 bg-[#030303]">
                  <div className="text-[#737373] text-[10px] mb-0.5">WASTED LOOP BURN</div>
                  <div
                    className={`font-bold text-base ${
                      roi.wasted_loop_cost_usd > 0 ? "text-[#ff3333]" : "text-white"
                    }`}
                  >
                    ${roi.wasted_loop_cost_usd.toFixed(4)}
                  </div>
                </div>
              </div>

              {/* Trajectory Evaluation Scores */}
              <div className="grid grid-cols-2 gap-2.5 border border-[#1c1c1c] bg-[#030303] p-2.5 text-[10px]">
                <div className="flex items-center justify-between">
                  <span className="text-[#888888] flex items-center gap-1">
                    <Award className="h-3 w-3 text-[#00ff66]" /> TASK SCORE:
                  </span>
                  <span className="text-white font-bold">
                    {(roi.task_completion_score * 100).toFixed(0)}%
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-[#888888] flex items-center gap-1">
                    <Award className="h-3 w-3 text-[#00e5ff]" /> TOOL ACCURACY:
                  </span>
                  <span className="text-white font-bold">
                    {(roi.tool_correctness_score * 100).toFixed(0)}%
                  </span>
                </div>
              </div>

              {/* Granular Ledger Breakdown */}
              <div className="border-t border-[#1c1c1c] pt-2.5 text-[11px] space-y-1.5 text-[#888888]">
                <div className="flex justify-between">
                  <span>LLM INFERENCE TOKENS:</span>
                  <span className="text-white font-semibold">${roi.llm_cost_usd.toFixed(4)}</span>
                </div>
                <div className="flex justify-between">
                  <span>MCP / TOOL INVOCATIONS:</span>
                  <span className="text-white font-semibold">${roi.tool_cost_usd.toFixed(4)}</span>
                </div>
                <div className="flex justify-between">
                  <span>CONTAINER COMPUTE INFRA:</span>
                  <span className="text-white font-semibold">${roi.infra_cost_usd.toFixed(4)}</span>
                </div>
                <div className="flex justify-between">
                  <span>HUMAN C2 INTERVENTION OVERHEAD:</span>
                  <span className="text-white font-semibold">
                    ${roi.c2_intervention_cost_usd.toFixed(4)}
                  </span>
                </div>
              </div>
            </div>
          ) : (
            <div className="flex-1 flex items-center justify-center text-[#666666] p-6">
              SELECT A SESSION TO COMPUTE FINANCIAL ROI ATTRIBUTION
            </div>
          )}
        </div>

        {/* Right: Hugging Face Open-Weight Pareto Frontier */}
        <div className="flex flex-col border border-[#222222] bg-[#060606] p-4">
          <div className="flex items-center justify-between pb-3 mb-3 border-b border-[#1a1a1a]">
            <span className="flex items-center gap-2 text-white font-bold">
              <Zap className="h-4 w-4 text-[#00e5ff]" />
              <span>HUGGING FACE PARETO MODEL SUBSTITUTIONS</span>
            </span>
            <span className="border border-[#00e5ff]/40 bg-[#001820] px-2 py-0.5 text-[10px] text-[#00e5ff]">
              GAIA BENCHMARK
            </span>
          </div>

          <div className="flex-1 flex flex-col space-y-2.5 overflow-y-auto max-h-[290px]">
            {recommendations.length > 0 ? (
              recommendations.map((rec, i) => (
                <div
                  key={i}
                  className="border border-[#222222] hover:border-[#00e5ff] p-3 bg-[#030303] transition-colors"
                >
                  <div className="flex items-center justify-between text-xs font-bold mb-1.5">
                    <div className="flex items-center gap-2">
                      <span className="text-white">{rec.candidate_model}</span>
                      <span className="border border-[#262626] bg-[#0c0c0c] px-1.5 py-0.5 text-[9px] text-[#a3a3a3] uppercase">
                        {rec.provider}
                      </span>
                    </div>
                    <span className="text-[#00ff66] flex items-center border border-[#00ff66]/40 bg-[#001808] px-2 py-0.5 text-[10px]">
                      <ArrowDownRight className="h-3 w-3 mr-0.5" />
                      -{rec.cost_savings_pct}% SPEND
                    </span>
                  </div>

                  <div className="grid grid-cols-2 gap-2 text-[10px] text-[#888888] mt-2 pt-2 border-t border-[#161616]">
                    <div>
                      TTFT LATENCY DELTA:{" "}
                      <span className="text-[#00e5ff] font-bold">
                        -{rec.latency_reduction_pct}%
                      </span>
                    </div>
                    <div className="text-right">
                      GAIA ACCURACY DELTA:{" "}
                      <span className="text-white font-bold">
                        {rec.benchmark_accuracy_delta >= 0
                          ? `+${rec.benchmark_accuracy_delta}`
                          : rec.benchmark_accuracy_delta}
                      </span>
                    </div>
                  </div>
                </div>
              ))
            ) : (
              <div className="space-y-2">
                {benchmarks.map((m, i) => (
                  <div
                    key={i}
                    className="flex justify-between items-center border border-[#1c1c1c] bg-[#030303] p-2.5 text-[11px]"
                  >
                    <span className="text-white font-bold">{m.model_name}</span>
                    <span className="text-[#a3a3a3]">
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
