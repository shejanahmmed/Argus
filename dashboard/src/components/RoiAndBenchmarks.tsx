import React from "react";
import { TrendingUp, Zap, ArrowDownRight, Award, CircleDollarSign } from "lucide-react";
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
    <div className="rounded-xl border border-zinc-800 bg-[#121215] flex flex-col shadow-sm">
      {/* Header */}
      <div className="flex items-center justify-between px-5 py-4 border-b border-zinc-800">
        <div className="flex items-center gap-2.5">
          <CircleDollarSign className="h-4 w-4 text-zinc-400" />
          <h2 className="text-sm font-semibold text-zinc-100">Financial ROI Attribution & Benchmarks</h2>
        </div>

        <div className="flex items-center gap-2">
          <span className="text-xs text-zinc-500 mr-1">Task Value:</span>
          <div className="flex items-center rounded-lg bg-zinc-900 p-0.5 border border-zinc-800">
            {VALUE_PRESETS.map((val) => (
              <button
                key={val}
                onClick={() => onChangeBusinessValue(val)}
                className={`rounded px-2.5 py-1 text-xs font-medium cursor-pointer transition-colors ${
                  businessValueUsd === val
                    ? "bg-zinc-800 text-white"
                    : "text-zinc-400 hover:text-zinc-200"
                }`}
              >
                ${val}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4 p-5">
        {/* Left: Financial Attribution & Trajectory Scores */}
        <div className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-4 flex flex-col">
          <div className="flex items-center justify-between pb-3 mb-3 border-b border-zinc-800">
            <span className="flex items-center gap-2 text-sm font-medium text-white">
              <TrendingUp className="h-4 w-4 text-emerald-400" />
              <span>Workflow Financial Breakdown</span>
            </span>
            {roi && (
              <span
                className={`rounded-full px-2 py-0.5 text-xs font-medium border ${
                  roi.task_completed
                    ? "border-emerald-500/20 bg-emerald-500/10 text-emerald-400"
                    : "border-amber-500/20 bg-amber-500/10 text-amber-400"
                }`}
              >
                {roi.task_completed ? "Goal Verified" : "In Progress"}
              </span>
            )}
          </div>

          {roi ? (
            <div className="space-y-4 flex-1 flex flex-col justify-between">
              <div className="grid grid-cols-2 gap-3 text-xs">
                <div className="rounded-lg border border-zinc-800 bg-zinc-950 p-3">
                  <div className="text-zinc-500 text-[11px] mb-0.5">Assigned Value</div>
                  <div className="text-white font-semibold text-base">
                    ${roi.assigned_business_value_usd.toFixed(2)}
                  </div>
                </div>
                <div className="rounded-lg border border-zinc-800 bg-zinc-950 p-3">
                  <div className="text-zinc-500 text-[11px] mb-0.5">Total Token & Tool Cost</div>
                  <div className="text-zinc-200 font-semibold text-base font-mono">
                    ${roi.total_cost_usd.toFixed(4)}
                  </div>
                </div>
                <div className="rounded-lg border border-zinc-800 bg-zinc-950 p-3">
                  <div className="text-zinc-500 text-[11px] mb-0.5">Net Workflow Value</div>
                  <div
                    className={`font-semibold text-base font-mono ${
                      roi.net_roi_usd >= 0 ? "text-emerald-400" : "text-rose-400"
                    }`}
                  >
                    ${roi.net_roi_usd.toFixed(2)}
                  </div>
                </div>
                <div className="rounded-lg border border-zinc-800 bg-zinc-950 p-3">
                  <div className="text-zinc-500 text-[11px] mb-0.5">Wasted Loop Burn</div>
                  <div
                    className={`font-semibold text-base font-mono ${
                      roi.wasted_loop_cost_usd > 0 ? "text-rose-400" : "text-zinc-200"
                    }`}
                  >
                    ${roi.wasted_loop_cost_usd.toFixed(4)}
                  </div>
                </div>
              </div>

              {/* Trajectory Scores */}
              <div className="grid grid-cols-2 gap-3 rounded-lg border border-zinc-800 bg-zinc-950 p-3 text-xs">
                <div className="flex items-center justify-between">
                  <span className="text-zinc-400 flex items-center gap-1.5">
                    <Award className="h-3.5 w-3.5 text-zinc-500" /> Goal Score:
                  </span>
                  <span className="text-white font-medium">
                    {(roi.task_completion_score * 100).toFixed(0)}%
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-zinc-400 flex items-center gap-1.5">
                    <Award className="h-3.5 w-3.5 text-zinc-500" /> Tool Accuracy:
                  </span>
                  <span className="text-white font-medium">
                    {(roi.tool_correctness_score * 100).toFixed(0)}%
                  </span>
                </div>
              </div>

              {/* Line items */}
              <div className="border-t border-zinc-800 pt-3 text-xs space-y-1.5 text-zinc-400 font-mono">
                <div className="flex justify-between">
                  <span className="text-zinc-500">LLM Inference:</span>
                  <span className="text-zinc-300">${roi.llm_cost_usd.toFixed(4)}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-zinc-500">MCP Tool Calls:</span>
                  <span className="text-zinc-300">${roi.tool_cost_usd.toFixed(4)}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-zinc-500">Container Infra:</span>
                  <span className="text-zinc-300">${roi.infra_cost_usd.toFixed(4)}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-zinc-500">C2 Operator Overhead:</span>
                  <span className="text-zinc-300">${roi.c2_intervention_cost_usd.toFixed(4)}</span>
                </div>
              </div>
            </div>
          ) : (
            <div className="flex-1 flex items-center justify-center text-xs text-zinc-500 p-6">
              Select a session to calculate financial attribution and ROI metrics
            </div>
          )}
        </div>

        {/* Right: Hugging Face Pareto Model Frontier */}
        <div className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-4 flex flex-col">
          <div className="flex items-center justify-between pb-3 mb-3 border-b border-zinc-800">
            <span className="flex items-center gap-2 text-sm font-medium text-white">
              <Zap className="h-4 w-4 text-sky-400" />
              <span>Hugging Face Pareto Frontier</span>
            </span>
            <span className="text-xs text-zinc-500">GAIA Benchmark Profiles</span>
          </div>

          <div className="space-y-2.5 overflow-y-auto max-h-[300px]">
            {recommendations.length > 0 ? (
              recommendations.map((rec, i) => (
                <div
                  key={i}
                  className="rounded-lg border border-zinc-800 bg-zinc-950 p-3 hover:border-zinc-700 transition-colors"
                >
                  <div className="flex items-center justify-between text-xs font-medium mb-1.5">
                    <div className="flex items-center gap-2">
                      <span className="text-zinc-100 font-semibold">{rec.candidate_model}</span>
                      <span className="rounded bg-zinc-800 px-1.5 py-0.5 text-[10px] text-zinc-400 uppercase">
                        {rec.provider}
                      </span>
                    </div>
                    <span className="rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 px-2 py-0.5 text-xs font-semibold flex items-center gap-0.5">
                      <ArrowDownRight className="h-3.5 w-3.5" />
                      -{rec.cost_savings_pct}% spend
                    </span>
                  </div>

                  <div className="flex items-center justify-between text-xs text-zinc-400 pt-1.5 border-t border-zinc-800/80 font-mono">
                    <span>Latency: -{rec.latency_reduction_pct}%</span>
                    <span>
                      Accuracy:{" "}
                      <span className="text-zinc-200">
                        {rec.benchmark_accuracy_delta >= 0
                          ? `+${rec.benchmark_accuracy_delta}`
                          : rec.benchmark_accuracy_delta}
                      </span>
                    </span>
                  </div>
                </div>
              ))
            ) : (
              <div className="space-y-2">
                {benchmarks.map((m, i) => (
                  <div
                    key={i}
                    className="flex justify-between items-center rounded-lg border border-zinc-800 bg-zinc-950 p-2.5 text-xs"
                  >
                    <span className="text-zinc-200 font-medium">{m.model_name}</span>
                    <span className="text-zinc-400 font-mono">
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
