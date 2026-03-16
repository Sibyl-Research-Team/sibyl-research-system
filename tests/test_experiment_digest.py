"""Tests for sibyl.experiment_digest module."""

import time

import pytest

from sibyl.experiment_digest import (
    analyze_gpu_efficiency,
    build_digest,
    compute_trend,
    detect_training_anomalies,
    format_digest_for_llm,
    generate_optimization_recommendations,
    parse_nvidia_smi_output,
)


# ═══════════════════════════════════════════
# compute_trend
# ═══════════════════════════════════════════


class TestComputeTrend:
    def test_insufficient_data(self):
        assert compute_trend([]) == "insufficient_data"
        assert compute_trend([0.5]) == "insufficient_data"

    def test_decreasing(self):
        assert compute_trend([1.0, 0.8, 0.6, 0.4]) == "decreasing"

    def test_flat(self):
        assert compute_trend([0.5, 0.5, 0.5, 0.5]) == "flat"

    def test_divergence(self):
        assert compute_trend([0.5, 0.4, 0.3, 0.8]) == "divergence"

    def test_plateau(self):
        # Fast decrease followed by very slow decrease
        losses = [1.0, 0.6, 0.3, 0.15, 0.14, 0.139, 0.138]
        result = compute_trend(losses, window=3)
        assert result in ("plateau", "flat")


# ═══════════════════════════════════════════
# detect_training_anomalies
# ═══════════════════════════════════════════


class TestDetectTrainingAnomalies:
    def test_empty_returns_empty(self):
        assert detect_training_anomalies([]) == []

    def test_loss_plateau_detected(self):
        entries = [
            {"task_id": "t1", "epoch": i, "loss": 0.5, "ts": 1000 + i}
            for i in range(5)
        ]
        anomalies = detect_training_anomalies(entries, plateau_epochs=3)
        types = [a["type"] for a in anomalies]
        assert "loss_plateau" in types

    def test_loss_divergence_detected(self):
        entries = [
            {"task_id": "t1", "epoch": 0, "loss": 0.5, "ts": 1000},
            {"task_id": "t1", "epoch": 1, "loss": 0.4, "ts": 1001},
            {"task_id": "t1", "epoch": 2, "loss": 1.2, "ts": 1002},
        ]
        anomalies = detect_training_anomalies(entries)
        types = [a["type"] for a in anomalies]
        assert "loss_divergence" in types

    def test_stale_progress_detected(self):
        old_ts = time.time() - 3600  # 1 hour ago
        entries = [{"task_id": "t1", "epoch": 0, "loss": 0.5, "ts": old_ts}]
        anomalies = detect_training_anomalies(entries, stale_minutes=30)
        types = [a["type"] for a in anomalies]
        assert "stale_progress" in types

    def test_no_anomalies_for_healthy_training(self):
        now = time.time()
        entries = [
            {"task_id": "t1", "epoch": i, "loss": 1.0 - i * 0.2, "ts": now - (5 - i) * 60}
            for i in range(5)
        ]
        anomalies = detect_training_anomalies(entries, plateau_epochs=3, stale_minutes=30)
        assert anomalies == []

    def test_multiple_tasks(self):
        entries = [
            {"task_id": "t1", "epoch": i, "loss": 0.5, "ts": 1000 + i}
            for i in range(4)
        ] + [
            {"task_id": "t2", "epoch": 0, "loss": 0.3, "ts": 1000},
            {"task_id": "t2", "epoch": 1, "loss": 0.9, "ts": 1001},  # divergence
        ]
        anomalies = detect_training_anomalies(entries, plateau_epochs=3)
        task_ids = {a["task_id"] for a in anomalies}
        assert "t1" in task_ids  # plateau
        assert "t2" in task_ids  # divergence


# ═══════════════════════════════════════════
# parse_nvidia_smi_output
# ═══════════════════════════════════════════


class TestParseNvidiaSmiOutput:
    def test_basic_format(self):
        output = "0, 8000\n1, 12000\n2, 100"
        gpus = parse_nvidia_smi_output(output)
        assert len(gpus) == 3
        assert gpus[0]["memory_used_mb"] == 8000
        assert gpus[2]["memory_used_mb"] == 100

    def test_with_total(self):
        output = "0, 8000, 24000\n1, 100, 24000"
        gpus = parse_nvidia_smi_output(output, include_total=True)
        assert gpus[0]["memory_total_mb"] == 24000

    def test_full_format(self):
        output = "0, 20000, 24000, 92\n1, 8000, 24000, 45"
        gpus = parse_nvidia_smi_output(output, include_total=True, include_utilization=True)
        assert gpus[0]["utilization_pct"] == 92
        assert gpus[1]["utilization_pct"] == 45

    def test_empty_output(self):
        assert parse_nvidia_smi_output("") == {}

    def test_malformed_lines_skipped(self):
        output = "garbage\n0, 8000\nbad data"
        gpus = parse_nvidia_smi_output(output)
        assert len(gpus) == 1


# ═══════════════════════════════════════════
# analyze_gpu_efficiency
# ═══════════════════════════════════════════


class TestAnalyzeGpuEfficiency:
    def test_free_gpu_detected(self):
        output = "0, 20000, 24000, 92\n1, 100, 24000, 0"
        result = analyze_gpu_efficiency(
            output,
            running_task_gpus={"task_1a": [0]},
        )
        assert 1 in result["free_gpus"]
        assert result["per_gpu"]["1"]["status"] == "free"

    def test_underutilized_gpu_detected(self):
        output = "0, 8000, 24000, 45"
        result = analyze_gpu_efficiency(
            output,
            running_task_gpus={"task_1a": [0]},
        )
        assert len(result["underutilized"]) == 1
        assert result["underutilized"][0]["task_id"] == "task_1a"
        assert result["per_gpu"]["0"]["status"] == "underutilized"

    def test_active_gpu(self):
        output = "0, 20000, 24000, 92"
        result = analyze_gpu_efficiency(
            output,
            running_task_gpus={"task_1a": [0]},
        )
        assert result["per_gpu"]["0"]["status"] == "active"
        assert result["free_gpus"] == []
        assert result["underutilized"] == []

    def test_recommendations_include_dispatch_for_free_gpus(self):
        output = "0, 20000, 24000, 92\n1, 100, 24000, 0"
        result = analyze_gpu_efficiency(
            output,
            running_task_gpus={"task_1a": [0]},
        )
        rec_types = [r["type"] for r in result["recommendations"]]
        assert "dispatch_queued" in rec_types


# ═══════════════════════════════════════════
# generate_optimization_recommendations
# ═══════════════════════════════════════════


class TestGenerateOptimizationRecommendations:
    def test_dispatch_for_free_gpus(self):
        analysis = {"free_gpus": [2, 3], "underutilized": [], "per_gpu": {}}
        recs = generate_optimization_recommendations(analysis)
        assert any(r["type"] == "dispatch_queued" for r in recs)

    def test_increase_batch_size_for_low_memory(self):
        analysis = {
            "free_gpus": [],
            "underutilized": [
                {"gpu_id": 0, "task_id": "t1", "memory_util_pct": 25, "compute_util_pct": 60},
            ],
            "per_gpu": {},
        }
        recs = generate_optimization_recommendations(analysis)
        assert any(r["type"] == "increase_batch_size" and r["task_id"] == "t1" for r in recs)

    def test_io_bound_detection(self):
        analysis = {
            "free_gpus": [],
            "underutilized": [
                {"gpu_id": 0, "task_id": "t1", "memory_util_pct": 80, "compute_util_pct": 30},
            ],
            "per_gpu": {},
        }
        recs = generate_optimization_recommendations(analysis)
        assert any(r["type"] == "io_bound" for r in recs)

    def test_no_recs_for_healthy_system(self):
        analysis = {"free_gpus": [], "underutilized": [], "per_gpu": {}}
        recs = generate_optimization_recommendations(analysis)
        assert recs == []


# ═══════════════════════════════════════════
# format_digest_for_llm
# ═══════════════════════════════════════════


class TestFormatDigestForLlm:
    def test_basic_format(self):
        digest = build_digest(
            gpu_analysis={
                "per_gpu": {
                    "0": {"memory_util_pct": 92, "status": "active"},
                    "1": {"memory_util_pct": 0, "status": "free"},
                },
                "free_gpus": [1],
                "underutilized": [],
            },
            training_anomalies=[],
            recommendations=[
                {"type": "dispatch_queued", "severity": "high", "reason": "GPU 1 空闲"},
            ],
            task_progress={
                "task_1a": {"epoch": 8, "total": 10, "loss": 0.342, "trend": "decreasing",
                            "mem_util_pct": 92, "gpu_ids": [0]},
            },
            elapsed_min=47,
            estimated_remaining_min=13,
        )
        text = format_digest_for_llm(digest)
        assert "47min" in text
        assert "13min" in text
        assert "FREE" in text
        assert "task_1a" in text
        assert "0.342" in text
        assert "GPU 1 空闲" in text

    def test_empty_digest(self):
        digest = build_digest({}, [], [])
        text = format_digest_for_llm(digest)
        assert "实验监控摘要" in text
