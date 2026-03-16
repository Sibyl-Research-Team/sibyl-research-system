"""Experiment monitoring digest — GPU efficiency analysis and training anomaly detection.

This module provides deterministic analysis of GPU utilization, training progress,
and optimization recommendations. It replaces LLM-based experiment monitoring
interpretation with code-first analysis.

Used by the experiment monitor daemon (bash script) to generate structured
digest data that the LLM can quickly act on.
"""

from __future__ import annotations

import re
from typing import Any


# ═══════════════════════════════════════════
# Training Trend Analysis
# ═══════════════════════════════════════════


def compute_trend(losses: list[float], window: int = 3) -> str:
    """Compute loss trend from a list of loss values.

    Returns one of: "decreasing", "flat", "plateau", "divergence", "insufficient_data"
    """
    if len(losses) < 2:
        return "insufficient_data"

    recent = losses[-window:] if len(losses) >= window else losses

    if len(recent) < 2:
        return "insufficient_data"

    # Check for divergence: last value > 1.5x the minimum of recent values
    if recent[-1] > 1.5 * min(recent[:-1]):
        return "divergence"

    # Check if decreasing: each value is less than or roughly equal to previous
    diffs = [recent[i + 1] - recent[i] for i in range(len(recent) - 1)]
    avg_diff = sum(diffs) / len(diffs)
    relative_change = abs(avg_diff) / max(abs(recent[0]), 1e-8)

    if relative_change < 0.01:
        return "flat"

    if avg_diff < 0:
        # Still decreasing but check if the rate has slowed significantly
        if len(losses) >= window * 2:
            early = losses[-(window * 2):-window]
            early_diffs = [early[i + 1] - early[i] for i in range(len(early) - 1)]
            early_avg = sum(early_diffs) / len(early_diffs) if early_diffs else avg_diff
            if early_avg < 0 and abs(avg_diff) < abs(early_avg) * 0.2:
                return "plateau"
        return "decreasing"

    # avg_diff > 0 but not divergence — plateau
    return "plateau"


def detect_training_anomalies(
    history_entries: list[dict],
    *,
    plateau_epochs: int = 3,
    divergence_ratio: float = 1.5,
    stale_minutes: int = 30,
) -> list[dict]:
    """Detect training anomalies from _PROGRESS.json history.

    Each entry: {"task_id": str, "epoch": int, "loss": float, "ts": int, ...}

    Returns list of anomaly dicts:
    [{"task_id": str, "type": str, "detail": str, "severity": str}]
    """
    anomalies: list[dict] = []
    if not history_entries:
        return anomalies

    # Group by task_id
    by_task: dict[str, list[dict]] = {}
    for entry in history_entries:
        tid = entry.get("task_id", "")
        if tid:
            by_task.setdefault(tid, []).append(entry)

    for task_id, entries in by_task.items():
        # Sort by epoch/timestamp
        entries.sort(key=lambda e: (e.get("epoch", 0), e.get("ts", 0)))
        losses = [e["loss"] for e in entries if "loss" in e and e["loss"] is not None]

        # Loss plateau detection
        if len(losses) >= plateau_epochs:
            recent = losses[-plateau_epochs:]
            if all(abs(recent[i + 1] - recent[i]) < 0.01 * max(abs(recent[0]), 1e-8)
                   for i in range(len(recent) - 1)):
                anomalies.append({
                    "task_id": task_id,
                    "type": "loss_plateau",
                    "detail": f"Loss flat for {plateau_epochs} epochs: {recent[-1]:.4f}",
                    "severity": "medium",
                })

        # Loss divergence detection
        if len(losses) >= 2:
            if losses[-1] > divergence_ratio * min(losses[:-1]):
                anomalies.append({
                    "task_id": task_id,
                    "type": "loss_divergence",
                    "detail": f"Loss jumped to {losses[-1]:.4f} (min was {min(losses[:-1]):.4f})",
                    "severity": "high",
                })

        # Stale progress detection
        if entries:
            latest_ts = entries[-1].get("ts", 0)
            if latest_ts > 0:
                import time
                age_min = (time.time() - latest_ts) / 60
                if age_min > stale_minutes:
                    anomalies.append({
                        "task_id": task_id,
                        "type": "stale_progress",
                        "detail": f"No update for {int(age_min)}min",
                        "severity": "medium",
                    })

    return anomalies


# ═══════════════════════════════════════════
# GPU Efficiency Analysis
# ═══════════════════════════════════════════


def parse_nvidia_smi_output(
    nvidia_smi_output: str,
    *,
    include_total: bool = False,
    include_utilization: bool = False,
) -> dict[int, dict]:
    """Parse nvidia-smi CSV output into per-GPU dicts.

    Supported formats:
    - "index, memory.used" (basic)
    - "index, memory.used, memory.total" (include_total)
    - "index, memory.used, memory.total, utilization.gpu" (full)
    """
    gpus: dict[int, dict] = {}
    for line in nvidia_smi_output.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 2:
            continue
        try:
            gpu_id = int(parts[0])
            mem_used = int(parts[1])
        except (ValueError, IndexError):
            continue

        gpu_info: dict[str, Any] = {
            "gpu_id": gpu_id,
            "memory_used_mb": mem_used,
        }

        if len(parts) >= 3:
            try:
                gpu_info["memory_total_mb"] = int(parts[2])
            except ValueError:
                pass

        if len(parts) >= 4:
            try:
                gpu_info["utilization_pct"] = int(parts[3])
            except ValueError:
                pass

        gpus[gpu_id] = gpu_info
    return gpus


def analyze_gpu_efficiency(
    nvidia_smi_output: str,
    gpu_profiles: dict[str, dict] | None = None,
    running_task_gpus: dict[str, list[int]] | None = None,
) -> dict:
    """Analyze per-GPU memory and compute efficiency.

    Args:
        nvidia_smi_output: Raw nvidia-smi CSV (index, mem.used, mem.total, util.gpu)
        gpu_profiles: task_id → _gpu_profile.json content
        running_task_gpus: task_id → [gpu_ids] mapping

    Returns structured analysis with per_gpu status, free_gpus list,
    underutilized list, and recommendations.
    """
    gpu_profiles = gpu_profiles or {}
    running_task_gpus = running_task_gpus or {}

    gpus = parse_nvidia_smi_output(
        nvidia_smi_output,
        include_total=True,
        include_utilization=True,
    )

    # Build GPU → task mapping
    gpu_to_task: dict[int, str] = {}
    for task_id, gpu_ids in running_task_gpus.items():
        for gid in gpu_ids:
            gpu_to_task[gid] = task_id

    per_gpu: dict[str, dict] = {}
    free_gpus: list[int] = []
    underutilized: list[dict] = []

    for gpu_id, info in sorted(gpus.items()):
        mem_used = info.get("memory_used_mb", 0)
        mem_total = info.get("memory_total_mb", 0)
        util_pct = info.get("utilization_pct", -1)
        task_id = gpu_to_task.get(gpu_id)

        mem_util_pct = int(100 * mem_used / mem_total) if mem_total > 0 else 0

        if mem_used < 500 and task_id is None:
            status = "free"
            free_gpus.append(gpu_id)
        elif mem_util_pct < 50:
            status = "underutilized"
            underutilized.append({
                "gpu_id": gpu_id,
                "task_id": task_id,
                "memory_util_pct": mem_util_pct,
                "compute_util_pct": util_pct if util_pct >= 0 else None,
            })
        else:
            status = "active"

        per_gpu[str(gpu_id)] = {
            "memory_used_mb": mem_used,
            "memory_total_mb": mem_total,
            "utilization_pct": util_pct if util_pct >= 0 else None,
            "memory_util_pct": mem_util_pct,
            "task_id": task_id,
            "status": status,
        }

    recommendations = generate_optimization_recommendations(
        {"per_gpu": per_gpu, "free_gpus": free_gpus, "underutilized": underutilized},
        gpu_profiles=gpu_profiles,
    )

    return {
        "per_gpu": per_gpu,
        "free_gpus": free_gpus,
        "underutilized": underutilized,
        "recommendations": recommendations,
    }


def generate_optimization_recommendations(
    gpu_analysis: dict,
    task_progress: dict[str, dict] | None = None,
    gpu_profiles: dict[str, dict] | None = None,
) -> list[dict]:
    """Generate optimization recommendations based on GPU efficiency analysis.

    Rules:
    - memory_util < 50% → increase_batch_size
    - memory_util < 30% → increase_batch_size + consider_multi_task
    - compute_util < 40% and memory_util > 70% → likely IO bound
    - free GPU detected → dispatch_queued (highest priority)
    """
    recommendations: list[dict] = []
    gpu_profiles = gpu_profiles or {}
    task_progress = task_progress or {}

    free_gpus = gpu_analysis.get("free_gpus", [])
    underutilized = gpu_analysis.get("underutilized", [])

    # Highest priority: free GPUs with queued tasks
    if free_gpus:
        recommendations.append({
            "type": "dispatch_queued",
            "task_id": None,
            "severity": "high",
            "reason": f"GPU {','.join(str(g) for g in free_gpus)} 空闲，有排队任务可调度",
            "gpu_ids": free_gpus,
        })

    # Underutilized GPUs
    for entry in underutilized:
        task_id = entry.get("task_id")
        mem_pct = entry.get("memory_util_pct", 0)
        compute_pct = entry.get("compute_util_pct")
        gpu_id = entry.get("gpu_id")

        if task_id is None:
            continue

        profile = gpu_profiles.get(task_id, {})
        current_bs = profile.get("batch_size", profile.get("optimal_batch_size", 0))

        if mem_pct < 30:
            recommendations.append({
                "type": "increase_batch_size",
                "task_id": task_id,
                "severity": "medium",
                "reason": (
                    f"GPU {gpu_id} 显存利用率仅 {mem_pct}%"
                    + (f"，当前 bs={current_bs}" if current_bs else "")
                    + "，建议增大 batch_size 或考虑多任务共享"
                ),
            })
        elif mem_pct < 50:
            recommendations.append({
                "type": "increase_batch_size",
                "task_id": task_id,
                "severity": "low",
                "reason": (
                    f"GPU {gpu_id} 显存利用率 {mem_pct}%"
                    + (f"，当前 bs={current_bs}" if current_bs else "")
                    + "，可考虑增大 batch_size"
                ),
            })

        # IO bound detection
        if compute_pct is not None and compute_pct < 40 and mem_pct > 70:
            recommendations.append({
                "type": "io_bound",
                "task_id": task_id,
                "severity": "low",
                "reason": (
                    f"GPU {gpu_id} 计算利用率 {compute_pct}% 但显存 {mem_pct}%，"
                    "可能 IO 瓶颈，建议增加 num_workers 或启用 prefetch"
                ),
            })

    return recommendations


# ═══════════════════════════════════════════
# Digest Formatting
# ═══════════════════════════════════════════


def format_digest_for_llm(digest: dict) -> str:
    """Format digest into a concise text summary for LLM quick assessment.

    Output example:
    === 实验监控摘要 (elapsed 47min, est. remaining 13min) ===
    GPU 状态: 0[92%] 1[87%] 2[FREE] 3[FREE]
    task_1a: GPU0, epoch 8/10, loss=0.342↓, 显存 86%
    task_1b: GPU1, epoch 3/10, loss=1.205→(plateau 3ep!), 显存 33%⚠
    ⚠ GPU 2,3 空闲，有排队任务可调度
    建议: 1) dispatch 排队任务到 GPU 2,3  2) 调参 task_1b
    """
    lines: list[str] = []

    elapsed = digest.get("elapsed_min", 0)
    remaining = digest.get("estimated_remaining_min", 0)
    lines.append(f"=== 实验监控摘要 (elapsed {elapsed}min, est. remaining {remaining}min) ===")

    # GPU status line
    gpu_analysis = digest.get("gpu_analysis", {})
    per_gpu = gpu_analysis.get("per_gpu", {})
    if per_gpu:
        gpu_parts = []
        for gid in sorted(per_gpu.keys(), key=lambda x: int(x)):
            info = per_gpu[gid]
            if info.get("status") == "free":
                gpu_parts.append(f"{gid}[FREE]")
            else:
                util = info.get("memory_util_pct", 0)
                gpu_parts.append(f"{gid}[{util}%]")
        lines.append(f"GPU 状态: {' '.join(gpu_parts)}")

    # Task status lines
    tasks = digest.get("tasks", {})
    anomalies_by_task: dict[str, list[str]] = {}
    for anomaly in digest.get("training_anomalies", []):
        tid = anomaly.get("task_id", "")
        anomalies_by_task.setdefault(tid, []).append(anomaly.get("type", ""))

    for task_id, info in tasks.items():
        epoch = info.get("epoch", "?")
        total = info.get("total", "?")
        loss = info.get("loss")
        trend = info.get("trend", "")
        mem_util = info.get("mem_util_pct", 0)
        gpu_ids = info.get("gpu_ids", [])

        trend_sym = {"decreasing": "↓", "flat": "→", "plateau": "→(plateau)", "divergence": "↑!"}.get(trend, "")
        loss_str = f"loss={loss:.4f}{trend_sym}" if loss is not None else ""
        gpu_str = f"GPU{','.join(str(g) for g in gpu_ids)}" if gpu_ids else ""

        task_anomalies = anomalies_by_task.get(task_id, [])
        warn = "⚠" if task_anomalies or mem_util < 50 else ""

        parts = [p for p in [gpu_str, f"epoch {epoch}/{total}", loss_str, f"显存 {mem_util}%{warn}"] if p]
        lines.append(f"{task_id}: {', '.join(parts)}")

    # Recommendations
    recs = digest.get("recommendations", [])
    if recs:
        lines.append("")
        for rec in recs:
            severity_prefix = "⚠" if rec.get("severity") == "high" else "·"
            lines.append(f"{severity_prefix} {rec.get('reason', '')}")

    return "\n".join(lines)


def build_digest(
    gpu_analysis: dict,
    training_anomalies: list[dict],
    recommendations: list[dict],
    task_progress: dict[str, dict] | None = None,
    *,
    elapsed_min: int = 0,
    estimated_remaining_min: int = 0,
) -> dict:
    """Combine all analysis results into a single digest dict."""
    return {
        "elapsed_min": elapsed_min,
        "estimated_remaining_min": estimated_remaining_min,
        "gpu_analysis": gpu_analysis,
        "training_anomalies": training_anomalies,
        "recommendations": recommendations,
        "tasks": task_progress or {},
    }
