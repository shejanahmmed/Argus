import React, { useState, useMemo, useEffect } from "react";
import {
  TrendingUp,
  Zap,
  ArrowDownRight,
  Award,
  CircleDollarSign,
  Filter,
} from "lucide-react";
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
const ACCURACY_PRESETS = [0.5, 0.6, 0.7, 0.8];

export const RoiAndBenchmarks: React.FC<RoiAndBenchmarksProps> = ({
  roi,
  benchmarks,
  recommendations,
  businessValueUsd,
  onChangeBusinessValue,
}) => {
  const [openWeightsOnly, setOpenWeightsOnly] = useState<boolean>(false);
  const [minAccuracy, setMinAccuracy] = useState<number>(0.5);
  const [customValueText, setCustomValueText] = useState<string>(businessValueUsd.toString());

  useEffect(() => {
    setCustomValueText(businessValueUsd.toString());
  }, [businessValueUsd]);

  const handleCustomValueChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const text = e.target.value;
    setCustomValueText(text);
    const parsed = parseFloat(text);
    if (!isNaN(parsed) && parsed >= 0) {
      onChangeBusinessValue(parsed);
    }
  };

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

  // Stacked cost bar calculation
  const totalCost = roi?.total_cost_usd || 0;
  const llmPct = totalCost > 0 ? ((roi?.llm_cost_usd || 0) / totalCost) * 100 : 0;
  const toolPct = totalCost > 0 ? ((roi?.tool_cost_usd || 0) / totalCost) * 100 : 0;
  const infraPct = totalCost > 0 ? ((roi?.infra_cost_usd || 0) / totalCost) * 100 : 0;
  const c2Pct = totalCost > 0 ? ((roi?.c2_intervention_cost_usd || 0) / totalCost) * 100 : 0;

  return (
    <div className="rounded-xl border border-[#222228] bg-[#111114] flex flex-col shadow-sm">
      {/* Panel Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between px-4 py-3 border-b border-[#222228] bg-[#0d0d10] rounded-t-xl gap-3">
        <div className="flex items-center gap-2.5">
          <div className="flex h-6 w-6 items-center justify-center rounded-md bg-[#18181b] border border-[#27272a] text-zinc-300">
            <CircleDollarSign className="h-3.5 w-3.5 text-zinc-400" />
          </div>
          <div className="flex items-center gap-2">
            <h2 className="text-xs font-semibold text-zinc-100 uppercase tracking-wider">
              Financial ROI Attribution & Benchmarks
            </h2>
          </div>
        </div>

        {/* Task Value Presets & Custom Input */}
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-[11px] font-mono text-zinc-500">Task Value:</span>
          <div className="flex items-center rounded-md bg-[#141418] p-0.5 border border-[#222228]">
            {VALUE_PRESETS.map((val) => (
              <button
                key={val}
                onClick={() => onChangeBusinessValue(val)}
                className={`rounded px-2 py-0.5 text-[11px] font-mono font-medium cursor-pointer transition-colors ${
                  businessValueUsd === val
                    ? "bg-[#222228] text-white shadow-2xs"
                    : "text-zinc-400 hover:text-zinc-200"
                }`}
              >
                ${val}
              </button>
            ))}
          </div>

          <div className="flex items-center gap-1 bg-[#141418] border border-[#222228] rounded-md px-2 py-0.5">
            <span className="text-zinc-500 text-[11px] font-mono">$</span>
            <input
              type="number"
              value={customValueText}
              onChange={handleCustomValueChange}
              placeholder="Custom"
              className="w-16 bg-transparent text-[11px] font-mono text-zinc-200 focus:outline-hidden text-right"
              min={0}
              step={10}
            />
          </div>
        </div>
      </div>

      {/* Dual Column Workspace */}
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4 p-4">
        {/* Left Column: Financial Attribution & Trajectory Performance */}
        <div className="rounded-lg border border-[#222228] bg-[#131317] p-3.5 flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between pb-2.5 mb-3 border-b border-[#1f1f26]">
              <span className="flex items-center gap-2 text-xs font-semibold text-zinc-100 uppercase tracking-wider">
                <TrendingUp className="h-3.5 w-3.5 text-emerald-400" />
                <span>Workflow Financial Breakdown</span>
              </span>
              {roi && (
                <span
                  className={`rounded-full px-2 py-0.5 text-[10px] font-mono font-medium border ${
                    roi.task_completed
                      ? "border-emerald-500/25 bg-emerald-500/10 text-emerald-400"
                      : "border-amber-500/25 bg-amber-500/10 text-amber-400"
                  }`}
                >
                  {roi.task_completed ? "Goal Verified" : "In Progress"}
                </span>
              )}
            </div>

            {roi ? (
              <div className="space-y-3">
                {/* 4 Metric Tiles */}
                <div className="grid grid-cols-2 gap-2.5 text-xs">
                  <div className="rounded-lg border border-[#222228] bg-[#09090b] p-2.5">
                    <div className="text-zinc-500 text-[10px] font-mono uppercase">
                      Assigned Valuation
                    </div>
                    <div className="text-white font-semibold text-sm font-mono mt-0.5">
                      ${roi.assigned_business_value_usd.toFixed(2)}
                    </div>
                    {roi.realized_business_value_usd !== undefined && (
                      <div className="text-[10px] text-zinc-400 mt-1 font-mono">
                        Realized:{" "}
                        <span className="text-emerald-400">
                          ${roi.realized_business_value_usd.toFixed(2)}
                        </span>
                      </div>
                    )}
                  </div>

                  <div className="rounded-lg border border-[#222228] bg-[#09090b] p-2.5">
                    <div className="text-zinc-500 text-[10px] font-mono uppercase">
                      Direct Execution Cost
                    </div>
                    <div className="text-zinc-200 font-semibold text-sm font-mono mt-0.5">
                      ${roi.total_cost_usd.toFixed(4)}
                    </div>
                    <div className="text-[10px] text-zinc-400 mt-1 font-mono">
                      4-tier FinOps spend
                    </div>
                  </div>

                  <div className="rounded-lg border border-[#222228] bg-[#09090b] p-2.5">
                    <div className="text-zinc-500 text-[10px] font-mono uppercase">
                      Net Workflow Value
                    </div>
                    <div
                      className={`font-semibold text-sm font-mono mt-0.5 ${
                        roi.net_roi_usd >= 0 ? "text-emerald-400" : "text-rose-400"
                      }`}
                    >
                      ${roi.net_roi_usd.toFixed(2)}
                    </div>
                    <div className="text-[10px] text-zinc-400 mt-1 font-mono">
                      {roi.roi_percentage >= 0
                        ? `+${roi.roi_percentage.toFixed(1)}%`
                        : `${roi.roi_percentage.toFixed(1)}%`}{" "}
                      ROI
                    </div>
                  </div>

                  <div className="rounded-lg border border-[#222228] bg-[#09090b] p-2.5">
                    <div className="text-zinc-500 text-[10px] font-mono uppercase">
                      Loop Waste Arrested
                    </div>
                    <div
                      className={`font-semibold text-sm font-mono mt-0.5 ${
                        roi.wasted_loop_cost_usd > 0 ? "text-rose-400" : "text-emerald-400"
                      }`}
                    >
                      ${roi.wasted_loop_cost_usd.toFixed(4)}
                    </div>
                    <div className="text-[10px] text-zinc-400 mt-1 font-mono">
                      {roi.wasted_loop_cost_usd > 0 ? "Arrested by breaker" : "Zero wasted burn"}
                    </div>
                  </div>
                </div>

                {/* Trajectory Performance Metrics */}
                <div className="grid grid-cols-2 gap-2.5 rounded-lg border border-[#222228] bg-[#09090b] p-2.5 text-xs font-mono">
                  <div className="flex items-center justify-between">
                    <span className="text-zinc-400 flex items-center gap-1.5 text-[11px]">
                      <Award className="h-3.5 w-3.5 text-zinc-500" /> Goal Score:
                    </span>
                    <span className="text-white font-medium text-xs">
                      {(roi.task_completion_score * 100).toFixed(0)}%
                    </span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-zinc-400 flex items-center gap-1.5 text-[11px]">
                      <Award className="h-3.5 w-3.5 text-zinc-500" /> Tool Accuracy:
                    </span>
                    <span className="text-white font-medium text-xs">
                      {(roi.tool_correctness_score * 100).toFixed(0)}%
                    </span>
                  </div>
                  {roi.wall_clock_duration_seconds !== undefined && (
                    <div className="col-span-2 pt-2 border-t border-[#1f1f26] flex justify-between text-[10px] text-zinc-500">
                      <span>Compute: {roi.wall_clock_duration_seconds.toFixed(1)}s</span>
                      <span>C2 Interventions: {roi.c2_interventions_count ?? 0}</span>
                      <span>Spans: {roi.total_spans_evaluated ?? 0}</span>
                    </div>
                  )}
                </div>

                {/* Stacked Proportional Cost Bar */}
                <div className="border-t border-[#1f1f26] pt-3 space-y-2">
                  <div className="flex items-center justify-between text-[10px] font-mono text-zinc-400 uppercase tracking-wider">
                    <span>4-Category Cost Allocation</span>
                    <span className="text-zinc-200">${totalCost.toFixed(4)} total</span>
                  </div>

                  {/* Stacked Bar */}
                  <div className="h-2 w-full rounded-full bg-[#18181b] overflow-hidden flex">
                    <div
                      style={{ width: `${llmPct}%` }}
                      className="bg-emerald-500 transition-all duration-300"
                      title={`LLM Inference: ${llmPct.toFixed(1)}%`}
                    />
                    <div
                      style={{ width: `${toolPct}%` }}
                      className="bg-sky-500 transition-all duration-300"
                      title={`Tool Calls: ${toolPct.toFixed(1)}%`}
                    />
                    <div
                      style={{ width: `${infraPct}%` }}
                      className="bg-amber-500 transition-all duration-300"
                      title={`Container Infra: ${infraPct.toFixed(1)}%`}
                    />
                    <div
                      style={{ width: `${c2Pct}%` }}
                      className="bg-purple-500 transition-all duration-300"
                      title={`C2 Overhead: ${c2Pct.toFixed(1)}%`}
                    />
                  </div>

                  {/* Allocation Legend */}
                  <div className="grid grid-cols-2 gap-2 text-[10px] font-mono text-zinc-400 pt-1">
                    <div className="flex items-center justify-between">
                      <span className="flex items-center gap-1.5">
                        <span className="h-2 w-2 rounded-full bg-emerald-500" />
                        <span>LLM Inference:</span>
                      </span>
                      <span className="text-zinc-200">${roi.llm_cost_usd.toFixed(4)}</span>
                    </div>
                    <div className="flex items-center justify-between">
                      <span className="flex items-center gap-1.5">
                        <span className="h-2 w-2 rounded-full bg-sky-500" />
                        <span>Tool Calls:</span>
                      </span>
                      <span className="text-zinc-200">${roi.tool_cost_usd.toFixed(4)}</span>
                    </div>
                    <div className="flex items-center justify-between">
                      <span className="flex items-center gap-1.5">
                        <span className="h-2 w-2 rounded-full bg-amber-500" />
                        <span>Container Infra:</span>
                      </span>
                      <span className="text-zinc-200">${roi.infra_cost_usd.toFixed(4)}</span>
                    </div>
                    <div className="flex items-center justify-between">
                      <span className="flex items-center gap-1.5">
                        <span className="h-2 w-2 rounded-full bg-purple-500" />
                        <span>C2 Overhead:</span>
                      </span>
                      <span className="text-zinc-200">
                        ${roi.c2_intervention_cost_usd.toFixed(4)}
                      </span>
                    </div>
                  </div>
                </div>
              </div>
            ) : (
              <div className="flex-1 flex items-center justify-center text-xs text-zinc-500 p-6">
                Select an agent session to calculate financial attribution and ROI metrics
              </div>
            )}
          </div>
        </div>

        {/* Right Column: Hugging Face Pareto Model Frontier */}
        <div className="rounded-lg border border-[#222228] bg-[#131317] p-3.5 flex flex-col">
          <div className="flex flex-col gap-2 pb-2.5 mb-3 border-b border-[#1f1f26]">
            <div className="flex items-center justify-between">
              <span className="flex items-center gap-2 text-xs font-semibold text-zinc-100 uppercase tracking-wider">
                <Zap className="h-3.5 w-3.5 text-sky-400" />
                <span>Hugging Face Pareto Frontier</span>
              </span>
              <span className="text-[10px] font-mono text-zinc-500">Open LLM & GAIA</span>
            </div>

            {/* Frontier Controls: Open-Weights toggle & Accuracy threshold */}
            <div className="flex items-center justify-between gap-2 pt-1 text-[11px]">
              <button
                onClick={() => setOpenWeightsOnly(!openWeightsOnly)}
                className={`flex items-center gap-1 px-2 py-0.5 rounded-md border font-mono transition-colors cursor-pointer ${
                  openWeightsOnly
                    ? "bg-purple-500/20 text-purple-300 border-purple-500/40 font-medium"
                    : "bg-[#09090b] text-zinc-400 border-[#222228] hover:text-zinc-200"
                }`}
              >
                <Filter className="h-3 w-3" />
                Open-Weights Only
              </button>

              <div className="flex items-center gap-1 text-zinc-400 font-mono text-[10px]">
                <span>Min Acc:</span>
                <div className="flex items-center rounded-md bg-[#09090b] p-0.5 border border-[#222228]">
                  {ACCURACY_PRESETS.map((acc) => (
                    <button
                      key={acc}
                      onClick={() => setMinAccuracy(acc)}
                      className={`px-1.5 py-0.5 rounded text-[10px] font-mono cursor-pointer transition-colors ${
                        minAccuracy === acc
                          ? "bg-[#222228] text-white font-medium shadow-2xs"
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

          <div className="space-y-2.5 overflow-y-auto max-h-[340px]">
            {filteredRecommendations.length > 0 ? (
              filteredRecommendations.map((rec, i) => (
                <div
                  key={i}
                  className="rounded-lg border border-[#222228] bg-[#09090b] p-3 hover:border-[#2e2e38] transition-colors"
                >
                  <div className="flex items-center justify-between text-xs font-medium mb-1.5">
                    <div className="flex items-center gap-1.5 flex-wrap">
                      <span className="text-zinc-100 font-medium text-xs font-mono">
                        {rec.display_name || rec.candidate_model}
                      </span>
                      <span className="rounded bg-[#1a1a20] px-1.5 py-0.5 text-[9px] font-mono text-zinc-400 border border-[#27272a] uppercase">
                        {rec.provider}
                      </span>
                      {rec.open_weights && (
                        <span className="rounded bg-purple-500/10 text-purple-400 border border-purple-500/20 px-1.5 py-0.2 text-[9px] font-mono font-medium">
                          OPEN
                        </span>
                      )}
                      {rec.is_pareto_optimal && (
                        <span className="rounded bg-sky-500/10 text-sky-400 border border-sky-500/20 px-1.5 py-0.2 text-[9px] font-mono font-medium">
                          PARETO
                        </span>
                      )}
                    </div>
                    <span className="rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 px-2 py-0.5 text-[11px] font-mono font-medium flex items-center gap-0.5 shrink-0">
                      <ArrowDownRight className="h-3 w-3" />
                      -{rec.cost_savings_pct}% spend
                    </span>
                  </div>

                  <div className="flex items-center justify-between text-[11px] text-zinc-400 pt-1.5 border-t border-[#1f1f26] font-mono">
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
                    className="flex justify-between items-center rounded-lg border border-[#222228] bg-[#09090b] p-2.5 text-xs"
                  >
                    <div className="flex items-center gap-1.5">
                      <span className="text-zinc-200 font-medium text-xs font-mono">
                        {m.display_name || m.model_name}
                      </span>
                      {m.open_weights && (
                        <span className="rounded bg-purple-500/10 text-purple-400 border border-purple-500/20 px-1 py-0.2 text-[9px] font-mono font-medium">
                          OPEN
                        </span>
                      )}
                    </div>
                    <span className="text-zinc-400 font-mono text-[10px]">
                      GAIA: {(m.gaia_accuracy * 100).toFixed(0)}% • TTFT: {m.ttft_ms}ms • $
                      {m.input_cost_per_1k}/1K
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
