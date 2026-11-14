"""Financial ROI attribution and benchmark evaluation components for Argus."""

from argus.attribution.evaluator import TrajectoryEvaluator
from argus.attribution.hf_benchmarks import (
    BASELINE_HF_MODELS,
    HuggingFaceBenchmarkAnalyzer,
    ModelBenchmarkProfile,
)
from argus.attribution.roi_engine import ROIEngine

__all__ = [
    "BASELINE_HF_MODELS",
    "HuggingFaceBenchmarkAnalyzer",
    "ModelBenchmarkProfile",
    "ROIEngine",
    "TrajectoryEvaluator",
]
