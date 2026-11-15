import React, { useState, useMemo } from "react";
import { TrendingUp, Zap, ArrowDownRight, Award, CircleDollarSign, Filter } from "lucide-react";
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
const ACCURACY_PRESETS = [0.5, 0.6, 0.7];

export const RoiAndBenchmarks: React.FC<RoiAndBenchmarksProps> = ({
  roi,
  benchmarks,
  recommendations,
  businessValueUsd,
  onChangeBusinessValue,
}) => {
  const [openWeightsOnly, setOpenWeightsOnly] = useState<boolean>(false);
  const [minAccuracy, setMinAccuracy] = useState<number>(0.5);

  const filteredRecommendations = useMemo(() => {
    return recommendations.filter((rec) => {
      if (openWeightsOnly && !rec.open_weights) {
        return false;
      }
      if (rec.candidate_gaia_accuracy !== undefined && rec.candidate_gaia_accuracy < minAccuracy) {
        return false;
      }
      return true;
    });
  }, [recommendations, openWeightsOnly, minAccuracy]);

  const filteredBenchmarks = useMemo(() => {
    return benchmarks.filter((m) => {
      if (openWeightsOnly && !m.open_weights) {
        return false;
      }
      if (m.gaia_accuracy < minAccuracy) {
        return false;
      }
      return true;
    });
  }, [benchmarks, openWeightsOnly, minAccuracy]);
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
                  {roi.realized_business_value_usd !== undefined && (
                    <div className="text-[10px] text-zinc-400 mt-1">
                      Realized: <span className="text-emerald-400 font-mono">${roi.realized_business_value_usd.toFixed(2)}</span>
                    </div>
                  )}
                </div>
                <div className="rounded-lg border border-zinc-800 bg-zinc-950 p-3">
                  <div className="text-zinc-500 text-[11px] mb-0.5">Total Execution Cost</div>
                  <div className="text-zinc-200 font-semibold text-base font-mono">
                    ${roi.total_cost_usd.toFixed(4)}
                  </div>
                  <div className="text-[10px] text-zinc-400 mt-1">
                    4-category FinOps total
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
                  <div className="text-[10px] text-zinc-400 mt-1 font-mono">
                    {roi.roi_percentage >= 0 ? `+${roi.roi_percentage.toFixed(1)}%` : `${roi.roi_percentage.toFixed(1)}%`} ROI
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
                  <div className="text-[10px] text-zinc-400 mt-1">
                    {roi.wasted_loop_cost_usd > 0 ? "Arrested by circuit breaker" : "Zero loop waste"}
                  </div>
                </div>
              </div>

              {/* Trajectory Scores & Operational Telemetry */}
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
                {roi.wall_clock_duration_seconds !== undefined && (
                  <div className="col-span-2 pt-2 border-t border-zinc-800/80 flex justify-between text-[11px] text-zinc-500 font-mono">
                    <span>Compute: {roi.wall_clock_duration_seconds.toFixed(1)}s</span>
                    <span>C2 Interventions: {roi.c2_interventions_count ?? 0}</span>
                    <span>Spans: {roi.total_spans_evaluated ?? 0}</span>
                  </div>
                )}
              </div>

              {/* 4 Granular Cost Categories Line Items */}
              <div className="border-t border-zinc-800 pt-3 text-xs space-y-1.5 text-zinc-400 font-mono">
                <div className="flex justify-between">
                  <span className="text-zinc-500">LLM Inference:</span>
                  <span className="text-zinc-300">
                    ${roi.llm_cost_usd.toFixed(4)}
                    {roi.total_cost_usd > 0 && (
                      <span className="text-zinc-500 text-[10px] ml-1.5">
                        ({((roi.llm_cost_usd / roi.total_cost_usd) * 100).toFixed(1)}%)
                      </span>
                    )}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-zinc-500">MCP Tool Calls:</span>
                  <span className="text-zinc-300">
                    ${roi.tool_cost_usd.toFixed(4)}
                    {roi.total_cost_usd > 0 && (
                      <span className="text-zinc-500 text-[10px] ml-1.5">
                        ({((roi.tool_cost_usd / roi.total_cost_usd) * 100).toFixed(1)}%)
                      </span>
                    )}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-zinc-500">Container Infra:</span>
                  <span className="text-zinc-300">
                    ${roi.infra_cost_usd.toFixed(4)}
                    {roi.total_cost_usd > 0 && (
                      <span className="text-zinc-500 text-[10px] ml-1.5">
                        ({((roi.infra_cost_usd / roi.total_cost_usd) * 100).toFixed(1)}%)
                      </span>
                    )}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-zinc-500">C2 Operator Overhead:</span>
                  <span className="text-zinc-300">
                    ${roi.c2_intervention_cost_usd.toFixed(4)}
                    {roi.total_cost_usd > 0 && (
                      <span className="text-zinc-500 text-[10px] ml-1.5">
                        ({((roi.c2_intervention_cost_usd / roi.total_cost_usd) * 100).toFixed(1)}%)
                      </span>
                    )}
                  </span>
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
          <div className="flex flex-col gap-2 pb-3 mb-3 border-b border-zinc-800">
            <div className="flex items-center justify-between">
              <span className="flex items-center gap-2 text-sm font-medium text-white">
                <Zap className="h-4 w-4 text-sky-400" />
                <span>Hugging Face Pareto Frontier</span>
              </span>
              <span className="text-xs text-zinc-500">Open LLM & GAIA</span>
            </div>

            {/* Frontier Controls: Open-Weights toggle & Accuracy threshold */}
            <div className="flex items-center justify-between gap-2 pt-1 text-[11px]">
              <button
                onClick={() => setOpenWeightsOnly(!openWeightsOnly)}
                className={`flex items-center gap-1 px-2 py-0.5 rounded border transition-colors cursor-pointer ${
                  openWeightsOnly
                    ? "bg-purple-500/20 text-purple-300 border-purple-500/40 font-medium"
                    : "bg-zinc-950 text-zinc-400 border-zinc-800 hover:text-zinc-200"
                }`}
              >
                <Filter className="h-3 w-3" />
                Open-Weights Only
              </button>

              <div className="flex items-center gap-1 text-zinc-400">
                <span>Min Acc:</span>
                <div className="flex items-center rounded bg-zinc-950 p-0.5 border border-zinc-800">
                  {ACCURACY_PRESETS.map((acc) => (
                    <button
                      key={acc}
                      onClick={() => setMinAccuracy(acc)}
                      className={`px-1.5 py-0.5 rounded text-[10px] cursor-pointer transition-colors ${
                        minAccuracy === acc
                          ? "bg-zinc-800 text-white font-medium"
                          : "text-zinc-500 hover:text-zinc-300"
                      }`}
                    >
                      {(acc * 100).toFixed(0)}%
                    </button>
                  ))}
                </div>
              </div>
            </div>
          </div>

          <div className="space-y-2.5 overflow-y-auto max-h-[300px]">
            {filteredRecommendations.length > 0 ? (
              filteredRecommendations.map((rec, i) => (
                <div
                  key={i}
                  className="rounded-lg border border-zinc-800 bg-zinc-950 p-3 hover:border-zinc-700 transition-colors"
                >
                  <div className="flex items-center justify-between text-xs font-medium mb-1.5">
                    <div className="flex items-center gap-1.5 flex-wrap">
                      <span className="text-zinc-100 font-semibold">
                        {rec.display_name || rec.candidate_model}
                      </span>
                      <span className="rounded bg-zinc-800 px-1.5 py-0.5 text-[10px] text-zinc-400 uppercase">
                        {rec.provider}
                      </span>
                      {rec.open_weights && (
                        <span className="rounded bg-purple-500/10 text-purple-400 border border-purple-500/20 px-1.5 py-0.2 text-[9px] font-semibold">
                          OPEN
                        </span>
                      )}
                      {rec.is_pareto_optimal && (
                        <span className="rounded bg-sky-500/10 text-sky-400 border border-sky-500/20 px-1.5 py-0.2 text-[9px] font-semibold">
                          PARETO
                        </span>
                      )}
                    </div>
                    <span className="rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 px-2 py-0.5 text-xs font-semibold flex items-center gap-0.5 shrink-0">
                      <ArrowDownRight className="h-3.5 w-3.5" />
                      -{rec.cost_savings_pct}% spend
                    </span>
                  </div>

                  <div className="flex items-center justify-between text-xs text-zinc-400 pt-1.5 border-t border-zinc-800/80 font-mono">
                    <span>Latency: -{rec.latency_reduction_pct}%</span>
                    {rec.throughput_gain_pct !== undefined && rec.throughput_gain_pct > 0 && (
                      <span className="hidden sm:inline">+{rec.throughput_gain_pct}% tok/s</span>
                    )}
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
                {filteredBenchmarks.map((m, i) => (
                  <div
                    key={i}
                    className="flex justify-between items-center rounded-lg border border-zinc-800 bg-zinc-950 p-2.5 text-xs"
                  >
                    <div className="flex items-center gap-1.5">
                      <span className="text-zinc-200 font-medium">{m.display_name || m.model_name}</span>
                      {m.open_weights && (
                        <span className="rounded bg-purple-500/10 text-purple-400 border border-purple-500/20 px-1 py-0.2 text-[9px] font-semibold">
                          OPEN
                        </span>
                      )}
                    </div>
                    <span className="text-zinc-400 font-mono text-[11px]">
                      GAIA: {(m.gaia_accuracy * 100).toFixed(0)}% • TTFT: {m.ttft_ms}ms • ${m.input_cost_per_1k}/1K
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
