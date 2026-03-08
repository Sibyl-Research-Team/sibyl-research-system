"""Tests for sibyl.gpu_scheduler module."""
import json
from pathlib import Path

import pytest

from sibyl.gpu_scheduler import (
    topo_sort_layers, assign_gpus, get_next_batch,
    estimate_batch_minutes, get_batch_info, validate_task_plan,
    nvidia_smi_query_cmd, parse_free_gpus, gpu_poll_wait_script,
    read_poll_result, _compute_calibration_ratio,
    experiment_monitor_script, read_monitor_result,
    register_running_tasks, unregister_running_task, get_running_gpu_ids,
)


# ══════════════════════════════════════════════
# Topological sort
# ══════════════════════════════════════════════

class TestTopoSortLayers:
    def test_empty(self):
        assert topo_sort_layers([]) == []

    def test_single_task(self):
        tasks = [{"id": "a", "depends_on": []}]
        layers = topo_sort_layers(tasks)
        assert len(layers) == 1
        assert layers[0][0]["id"] == "a"

    def test_independent_tasks(self):
        tasks = [
            {"id": "a", "depends_on": []},
            {"id": "b", "depends_on": []},
            {"id": "c", "depends_on": []},
        ]
        layers = topo_sort_layers(tasks)
        assert len(layers) == 1
        assert len(layers[0]) == 3

    def test_linear_chain(self):
        tasks = [
            {"id": "a", "depends_on": []},
            {"id": "b", "depends_on": ["a"]},
            {"id": "c", "depends_on": ["b"]},
        ]
        layers = topo_sort_layers(tasks)
        assert len(layers) == 3
        assert layers[0][0]["id"] == "a"
        assert layers[1][0]["id"] == "b"
        assert layers[2][0]["id"] == "c"

    def test_diamond_dag(self):
        tasks = [
            {"id": "a", "depends_on": []},
            {"id": "b", "depends_on": ["a"]},
            {"id": "c", "depends_on": ["a"]},
            {"id": "d", "depends_on": ["b", "c"]},
        ]
        layers = topo_sort_layers(tasks)
        assert len(layers) == 3
        assert layers[0][0]["id"] == "a"
        ids_1 = {t["id"] for t in layers[1]}
        assert ids_1 == {"b", "c"}
        assert layers[2][0]["id"] == "d"

    def test_missing_dep_ignored(self):
        """Dependencies referencing non-existent tasks should be ignored."""
        tasks = [
            {"id": "a", "depends_on": ["nonexistent"]},
        ]
        layers = topo_sort_layers(tasks)
        assert len(layers) == 1

    def test_no_depends_on_key(self):
        tasks = [{"id": "a"}, {"id": "b"}]
        layers = topo_sort_layers(tasks)
        assert len(layers) == 1
        assert len(layers[0]) == 2


# ══════════════════════════════════════════════
# GPU assignment
# ══════════════════════════════════════════════

class TestAssignGpus:
    def test_basic_assignment(self):
        tasks = [{"id": "a"}, {"id": "b"}]
        result = assign_gpus(tasks, [0, 1, 2, 3])
        assert len(result) == 2
        assert result[0]["task_ids"] == ["a"]
        assert result[0]["gpu_ids"] == [0]
        assert result[1]["task_ids"] == ["b"]
        assert result[1]["gpu_ids"] == [1]

    def test_per_task_gpu_count(self):
        """Each task declares its own gpu_count."""
        tasks = [
            {"id": "a", "gpu_count": 2},
            {"id": "b", "gpu_count": 1},
        ]
        result = assign_gpus(tasks, [0, 1, 2, 3])
        assert len(result) == 2
        assert result[0]["gpu_ids"] == [0, 1]  # task a gets 2 GPUs
        assert result[1]["gpu_ids"] == [2]      # task b gets 1 GPU

    def test_mixed_gpu_counts_exhaust(self):
        """Tasks with different gpu_count, not enough GPUs for all."""
        tasks = [
            {"id": "a", "gpu_count": 2},
            {"id": "b", "gpu_count": 2},
            {"id": "c", "gpu_count": 1},
        ]
        result = assign_gpus(tasks, [0, 1, 2, 3])
        assert len(result) == 2  # a=2, b=2, c can't fit
        assert result[0]["gpu_ids"] == [0, 1]
        assert result[1]["gpu_ids"] == [2, 3]

    def test_default_gpus_per_task_fallback(self):
        """Tasks without gpu_count use the default."""
        tasks = [{"id": "a"}, {"id": "b"}]
        result = assign_gpus(tasks, [0, 1, 2, 3], default_gpus_per_task=2)
        assert len(result) == 2
        assert result[0]["gpu_ids"] == [0, 1]
        assert result[1]["gpu_ids"] == [2, 3]

    def test_task_gpu_count_overrides_default(self):
        """Per-task gpu_count takes precedence over default."""
        tasks = [
            {"id": "a", "gpu_count": 1},  # overrides default 2
            {"id": "b"},                   # uses default 2
        ]
        result = assign_gpus(tasks, [0, 1, 2, 3], default_gpus_per_task=2)
        assert len(result) == 2
        assert result[0]["gpu_ids"] == [0]
        assert result[1]["gpu_ids"] == [1, 2]

    def test_more_tasks_than_gpus(self):
        tasks = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
        result = assign_gpus(tasks, [0, 1])
        assert len(result) == 2  # only 2 GPUs available

    def test_task_needs_more_than_total_gpus(self):
        """Task needs 4 GPUs but only 2 available → gets all GPUs."""
        tasks = [{"id": "a", "gpu_count": 4}]
        result = assign_gpus(tasks, [0, 1])
        assert len(result) == 1
        assert result[0]["gpu_ids"] == [0, 1]

    def test_empty_inputs(self):
        assert assign_gpus([], [0, 1]) == []
        assert assign_gpus([{"id": "a"}], []) == []


# ══════════════════════════════════════════════
# Time estimation
# ══════════════════════════════════════════════

class TestEstimateBatchMinutes:
    def test_default(self):
        assert estimate_batch_minutes([], []) == 10

    def test_uses_task_estimate(self):
        tasks = [
            {"id": "a", "estimated_minutes": 30},
            {"id": "b", "estimated_minutes": 60},
        ]
        batch = [
            {"task_ids": ["a"], "gpu_ids": [0]},
            {"task_ids": ["b"], "gpu_ids": [1]},
        ]
        assert estimate_batch_minutes(batch, tasks) == 60  # max

    def test_missing_estimate_uses_default(self):
        tasks = [{"id": "a"}]
        batch = [{"task_ids": ["a"], "gpu_ids": [0]}]
        assert estimate_batch_minutes(batch, tasks, default_minutes=15) == 15

    def test_single_long_task(self):
        tasks = [
            {"id": "a", "estimated_minutes": 120},
            {"id": "b", "estimated_minutes": 5},
        ]
        batch = [{"task_ids": ["a"], "gpu_ids": [0]}]
        assert estimate_batch_minutes(batch, tasks) == 120


# ══════════════════════════════════════════════
# Batch scheduling (get_next_batch)
# ══════════════════════════════════════════════

class TestGetNextBatch:
    def test_no_task_plan(self, tmp_path):
        """No task_plan.json → returns None (fallback)."""
        result = get_next_batch(tmp_path, [0, 1])
        assert result is None

    def test_empty_tasks(self, tmp_path):
        plan_dir = tmp_path / "plan"
        plan_dir.mkdir()
        (plan_dir / "task_plan.json").write_text(json.dumps({"tasks": []}))
        result = get_next_batch(tmp_path, [0, 1])
        assert result is None

    def test_no_tasks_key(self, tmp_path):
        plan_dir = tmp_path / "plan"
        plan_dir.mkdir()
        (plan_dir / "task_plan.json").write_text(json.dumps({"description": "test"}))
        result = get_next_batch(tmp_path, [0, 1])
        assert result is None

    def test_first_batch(self, tmp_path):
        plan_dir = tmp_path / "plan"
        plan_dir.mkdir()
        tasks = [
            {"id": "a", "depends_on": []},
            {"id": "b", "depends_on": []},
            {"id": "c", "depends_on": ["a", "b"]},
        ]
        (plan_dir / "task_plan.json").write_text(json.dumps({"tasks": tasks}))

        result = get_next_batch(tmp_path, [0, 1, 2, 3])
        assert result is not None
        assert len(result) == 2  # a and b are ready
        ids = [r["task_ids"][0] for r in result]
        assert set(ids) == {"a", "b"}

    def test_second_batch_after_progress(self, tmp_path):
        plan_dir = tmp_path / "plan"
        plan_dir.mkdir()
        tasks = [
            {"id": "a", "depends_on": []},
            {"id": "b", "depends_on": []},
            {"id": "c", "depends_on": ["a", "b"]},
        ]
        (plan_dir / "task_plan.json").write_text(json.dumps({"tasks": tasks}))

        # Mark a and b complete
        exp_dir = tmp_path / "exp"
        exp_dir.mkdir()
        (exp_dir / "gpu_progress.json").write_text(json.dumps({
            "completed": ["a", "b"], "failed": []
        }))

        result = get_next_batch(tmp_path, [0, 1, 2, 3])
        assert result is not None
        assert len(result) == 1
        assert result[0]["task_ids"] == ["c"]

    def test_all_complete(self, tmp_path):
        plan_dir = tmp_path / "plan"
        plan_dir.mkdir()
        tasks = [{"id": "a", "depends_on": []}]
        (plan_dir / "task_plan.json").write_text(json.dumps({"tasks": tasks}))

        exp_dir = tmp_path / "exp"
        exp_dir.mkdir()
        (exp_dir / "gpu_progress.json").write_text(json.dumps({
            "completed": ["a"], "failed": []
        }))

        result = get_next_batch(tmp_path, [0, 1])
        assert result is None  # all done

    def test_blocked_tasks(self, tmp_path):
        plan_dir = tmp_path / "plan"
        plan_dir.mkdir()
        tasks = [
            {"id": "a", "depends_on": []},
            {"id": "c", "depends_on": []},
            {"id": "b", "depends_on": ["a", "c"]},
        ]
        (plan_dir / "task_plan.json").write_text(json.dumps({"tasks": tasks}))
        exp_dir = tmp_path / "exp"
        exp_dir.mkdir(exist_ok=True)
        (exp_dir / "gpu_progress.json").write_text(json.dumps({
            "completed": ["a"], "failed": []
        }))

        result = get_next_batch(tmp_path, [0, 1])
        # c is ready (no deps, not completed), b is blocked on c
        assert result is not None
        assert len(result) == 1
        assert result[0]["task_ids"] == ["c"]

    def test_per_task_gpu_count(self, tmp_path):
        """Tasks with per-task gpu_count are respected."""
        plan_dir = tmp_path / "plan"
        plan_dir.mkdir()
        tasks = [
            {"id": "a", "depends_on": [], "gpu_count": 2},
            {"id": "b", "depends_on": [], "gpu_count": 2},
        ]
        (plan_dir / "task_plan.json").write_text(json.dumps({"tasks": tasks}))

        result = get_next_batch(tmp_path, [0, 1, 2, 3])
        assert len(result) == 2
        assert result[0]["gpu_ids"] == [0, 1]
        assert result[1]["gpu_ids"] == [2, 3]

    def test_corrupt_json(self, tmp_path):
        plan_dir = tmp_path / "plan"
        plan_dir.mkdir()
        (plan_dir / "task_plan.json").write_text("not valid json {{{")
        result = get_next_batch(tmp_path, [0, 1])
        assert result is None


# ══════════════════════════════════════════════
# Batch info (with timing metadata)
# ══════════════════════════════════════════════

class TestGetBatchInfo:
    def test_no_task_plan(self, tmp_path):
        assert get_batch_info(tmp_path, [0, 1]) is None

    def test_returns_metadata(self, tmp_path):
        plan_dir = tmp_path / "plan"
        plan_dir.mkdir()
        tasks = [
            {"id": "a", "depends_on": [], "estimated_minutes": 30},
            {"id": "b", "depends_on": [], "estimated_minutes": 60},
            {"id": "c", "depends_on": ["a", "b"], "estimated_minutes": 15},
        ]
        (plan_dir / "task_plan.json").write_text(json.dumps({"tasks": tasks}))

        info = get_batch_info(tmp_path, [0, 1, 2, 3])
        assert info is not None
        assert len(info["batch"]) == 2
        assert info["estimated_minutes"] == 60  # max of a=30, b=60
        assert info["remaining_count"] == 3
        assert info["total_count"] == 3

    def test_progress_updates_counts(self, tmp_path):
        plan_dir = tmp_path / "plan"
        plan_dir.mkdir()
        tasks = [
            {"id": "a", "depends_on": []},
            {"id": "b", "depends_on": ["a"]},
        ]
        (plan_dir / "task_plan.json").write_text(json.dumps({"tasks": tasks}))
        exp_dir = tmp_path / "exp"
        exp_dir.mkdir()
        (exp_dir / "gpu_progress.json").write_text(json.dumps({
            "completed": ["a"], "failed": []
        }))

        info = get_batch_info(tmp_path, [0, 1])
        assert info["remaining_count"] == 1
        assert info["total_count"] == 2
        assert len(info["batch"]) == 1

    def test_all_complete_returns_none(self, tmp_path):
        plan_dir = tmp_path / "plan"
        plan_dir.mkdir()
        tasks = [{"id": "a", "depends_on": []}]
        (plan_dir / "task_plan.json").write_text(json.dumps({"tasks": tasks}))
        exp_dir = tmp_path / "exp"
        exp_dir.mkdir()
        (exp_dir / "gpu_progress.json").write_text(json.dumps({
            "completed": ["a"], "failed": []
        }))

        assert get_batch_info(tmp_path, [0, 1]) is None

    def test_blocked_returns_empty_batch(self, tmp_path):
        plan_dir = tmp_path / "plan"
        plan_dir.mkdir()
        tasks = [
            {"id": "a", "depends_on": ["b"]},
            {"id": "b", "depends_on": ["a"]},  # circular → both blocked
        ]
        (plan_dir / "task_plan.json").write_text(json.dumps({"tasks": tasks}))

        info = get_batch_info(tmp_path, [0, 1])
        assert info is not None
        assert info["batch"] == []
        assert info["remaining_count"] == 2


# ══════════════════════════════════════════════
# Task plan validation
# ══════════════════════════════════════════════

class TestValidateTaskPlan:
    def test_complete_tasks(self):
        tasks = [
            {"id": "a", "gpu_count": 1, "estimated_minutes": 30},
            {"id": "b", "gpu_count": 2, "estimated_minutes": 60},
        ]
        assert validate_task_plan(tasks) == []

    def test_missing_gpu_count(self):
        tasks = [
            {"id": "a", "estimated_minutes": 30},
            {"id": "b", "gpu_count": 2, "estimated_minutes": 60},
        ]
        assert validate_task_plan(tasks) == ["a"]

    def test_missing_estimated_minutes(self):
        tasks = [
            {"id": "a", "gpu_count": 1},
            {"id": "b", "gpu_count": 2},
        ]
        assert validate_task_plan(tasks) == ["a", "b"]

    def test_missing_both(self):
        tasks = [{"id": "a"}, {"id": "b"}]
        assert validate_task_plan(tasks) == ["a", "b"]

    def test_null_values_detected(self):
        tasks = [{"id": "a", "gpu_count": None, "estimated_minutes": 30}]
        assert validate_task_plan(tasks) == ["a"]

    def test_empty_tasks(self):
        assert validate_task_plan([]) == []


# ══════════════════════════════════════════════
# GPU polling: nvidia_smi_query_cmd
# ══════════════════════════════════════════════

class TestNvidiaSmiQueryCmd:
    def test_returns_valid_command(self):
        cmd = nvidia_smi_query_cmd()
        assert "nvidia-smi" in cmd
        assert "--query-gpu=index,memory.used" in cmd
        assert "noheader" in cmd
        assert "nounits" in cmd


# ══════════════════════════════════════════════
# GPU polling: parse_free_gpus
# ══════════════════════════════════════════════

class TestParseFreeGpus:
    def test_basic_parsing(self):
        output = "0, 512\n1, 15234\n2, 128\n3, 22000"
        free = parse_free_gpus(output, threshold_mb=2000)
        assert free == [0, 2]

    def test_all_free(self):
        output = "0, 100\n1, 200\n2, 50\n3, 300"
        free = parse_free_gpus(output, threshold_mb=2000)
        assert free == [0, 1, 2, 3]

    def test_none_free(self):
        output = "0, 5000\n1, 8000\n2, 12000\n3, 22000"
        free = parse_free_gpus(output, threshold_mb=2000)
        assert free == []

    def test_max_gpus_caps_result(self):
        """max_gpus limits how many free GPUs are returned."""
        output = "0, 100\n1, 200\n2, 100\n3, 100"
        free = parse_free_gpus(output, threshold_mb=2000, max_gpus=2)
        assert free == [0, 1]  # all 4 are free but capped to 2

    def test_max_gpus_zero_no_limit(self):
        """max_gpus=0 returns all free GPUs."""
        output = "0, 100\n1, 200\n2, 100\n3, 100\n4, 50\n5, 50"
        free = parse_free_gpus(output, threshold_mb=2000, max_gpus=0)
        assert free == [0, 1, 2, 3, 4, 5]

    def test_empty_output(self):
        free = parse_free_gpus("", threshold_mb=2000)
        assert free == []

    def test_whitespace_and_blank_lines(self):
        output = "\n  0, 100  \n\n  1, 5000  \n  "
        free = parse_free_gpus(output, threshold_mb=2000)
        assert free == [0]

    def test_threshold_boundary(self):
        """Memory exactly at threshold is NOT free (< not <=)."""
        output = "0, 2000\n1, 1999"
        free = parse_free_gpus(output, threshold_mb=2000)
        assert free == [1]

    def test_malformed_lines_skipped(self):
        output = "garbage line\n0, 100\nbad\n1, 200"
        free = parse_free_gpus(output, threshold_mb=2000)
        assert free == [0, 1]

    def test_float_memory_values(self):
        """nvidia-smi might output floats in some locales."""
        output = "0, 512.5\n1, 3000.7"
        free = parse_free_gpus(output, threshold_mb=2000)
        assert free == [0]

    def test_sorted_output(self):
        output = "3, 100\n1, 200\n0, 50"
        free = parse_free_gpus(output, threshold_mb=2000)
        assert free == [0, 1, 3]  # sorted

    def test_custom_threshold(self):
        output = "0, 500\n1, 7000"
        free = parse_free_gpus(output, threshold_mb=1000)
        assert free == [0]

    def test_8gpu_machine_picks_any_free(self):
        """On an 8-GPU machine, returns any free GPU regardless of index."""
        output = "0, 50000\n1, 50000\n2, 100\n3, 50000\n4, 50000\n5, 200\n6, 50000\n7, 300"
        free = parse_free_gpus(output, threshold_mb=2000)
        assert free == [2, 5, 7]  # any GPU can be free

    def test_8gpu_capped(self):
        """On an 8-GPU machine with max_gpus=4, only returns first 4 free."""
        output = "0, 100\n1, 100\n2, 100\n3, 100\n4, 100\n5, 100\n6, 100\n7, 100"
        free = parse_free_gpus(output, threshold_mb=2000, max_gpus=4)
        assert free == [0, 1, 2, 3]


# ══════════════════════════════════════════════
# GPU polling: gpu_poll_wait_script
# ══════════════════════════════════════════════

class TestGpuPollWaitScript:
    def test_generates_bash_script(self):
        script = gpu_poll_wait_script("gpu-server", [0, 1, 2, 3])
        assert "#!/bin/bash" in script
        assert "nvidia-smi" in script
        assert "gpu-server" in script
        assert "0,1,2,3" in script

    def test_infinite_poll_default(self):
        """Default max_polls=0 generates while-true loop (no timeout)."""
        script = gpu_poll_wait_script("host", [0, 1])
        assert "while true" in script
        assert "Timeout" not in script
        assert "unlimited" in script

    def test_finite_poll(self):
        """max_polls > 0 generates for loop with timeout."""
        script = gpu_poll_wait_script("host", [0], max_polls=10)
        assert "seq 1 10" in script
        assert "Timeout" in script

    def test_custom_parameters(self):
        script = gpu_poll_wait_script(
            ssh_server="myserver",
            candidate_gpu_ids=[0, 2],
            threshold_mb=4000,
            poll_interval_sec=30,
            max_polls=10,
            marker_file="/tmp/test_marker.json",
        )
        assert "myserver" in script
        assert "0,2" in script
        assert "4000" in script
        assert "30" in script  # poll interval
        assert "seq 1 10" in script  # finite loop
        assert "/tmp/test_marker.json" in script

    def test_marker_file_path(self):
        script = gpu_poll_wait_script(
            "host", [0], marker_file="/custom/path.json"
        )
        assert "/custom/path.json" in script

    def test_single_gpu(self):
        script = gpu_poll_wait_script("host", [2])
        assert ",2," in script  # in case pattern


# ══════════════════════════════════════════════
# GPU polling: read_poll_result
# ══════════════════════════════════════════════

class TestReadPollResult:
    def test_file_not_found(self, tmp_path):
        result = read_poll_result(str(tmp_path / "nonexistent.json"))
        assert result is None

    def test_reads_valid_json(self, tmp_path):
        marker = tmp_path / "marker.json"
        marker.write_text(json.dumps({"free_gpus": [0, 2], "poll_count": 3}))
        result = read_poll_result(str(marker))
        assert result == [0, 2]

    def test_empty_free_gpus(self, tmp_path):
        marker = tmp_path / "marker.json"
        marker.write_text(json.dumps({"free_gpus": [], "poll_count": 1}))
        result = read_poll_result(str(marker))
        assert result == []

    def test_corrupt_json(self, tmp_path):
        marker = tmp_path / "marker.json"
        marker.write_text("not json {{{")
        result = read_poll_result(str(marker))
        assert result is None

    def test_missing_key(self, tmp_path):
        marker = tmp_path / "marker.json"
        marker.write_text(json.dumps({"poll_count": 5}))
        result = read_poll_result(str(marker))
        assert result == []  # default from .get()


# ══════════════════════════════════════════════
# Aggressive GPU mode
# ══════════════════════════════════════════════

class TestAggressiveMode:
    """Test aggressive GPU claiming based on VRAM usage percentage."""

    def test_normal_mode_ignores_high_usage(self):
        # GPU 0: 5000/24000 MB (20%) — above 2000MB threshold, normal mode rejects
        output = "0, 5000, 24000\n1, 100, 24000"
        free = parse_free_gpus(output, threshold_mb=2000, aggressive_mode=False)
        assert free == [1]  # only GPU 1 is truly free

    def test_aggressive_mode_claims_low_pct(self):
        # GPU 0: 5000/24000 MB (20.8%) — above 2000MB but below 25% → claimed
        # GPU 1: 100/24000 MB — below 2000MB → free normally
        # GPU 2: 8000/24000 MB (33%) — above both thresholds → not claimed
        output = "0, 5000, 24000\n1, 100, 24000\n2, 8000, 24000"
        free = parse_free_gpus(
            output, threshold_mb=2000,
            aggressive_mode=True, aggressive_threshold_pct=25,
        )
        assert free == [0, 1]

    def test_aggressive_mode_respects_max_gpus(self):
        output = "0, 3000, 24000\n1, 4000, 24000\n2, 100, 24000"
        free = parse_free_gpus(
            output, threshold_mb=2000, max_gpus=1,
            aggressive_mode=True, aggressive_threshold_pct=25,
        )
        assert len(free) == 1

    def test_aggressive_mode_without_total_column(self):
        # Only 2 columns → aggressive check skipped, falls back to normal
        output = "0, 5000\n1, 100"
        free = parse_free_gpus(
            output, threshold_mb=2000,
            aggressive_mode=True, aggressive_threshold_pct=25,
        )
        assert free == [1]  # only normal threshold applies

    def test_aggressive_threshold_boundary(self):
        # GPU at exactly 25% → not claimed (must be strictly less than)
        output = "0, 6000, 24000"  # 6000/24000 = 25.0%
        free = parse_free_gpus(
            output, threshold_mb=2000,
            aggressive_mode=True, aggressive_threshold_pct=25,
        )
        assert free == []

    def test_aggressive_just_below_threshold(self):
        # GPU at 24.9% → claimed
        output = "0, 5976, 24000"  # 5976/24000 = 24.9%
        free = parse_free_gpus(
            output, threshold_mb=2000,
            aggressive_mode=True, aggressive_threshold_pct=25,
        )
        assert free == [0]

    def test_nvidia_smi_query_includes_total(self):
        cmd = nvidia_smi_query_cmd(include_total=True)
        assert "memory.total" in cmd

    def test_nvidia_smi_query_no_total_by_default(self):
        cmd = nvidia_smi_query_cmd()
        assert "memory.total" not in cmd

    def test_poll_script_aggressive_mode(self):
        script = gpu_poll_wait_script(
            ssh_server="gpu-server",
            candidate_gpu_ids=[0, 1],
            aggressive_mode=True,
            aggressive_threshold_pct=25,
        )
        assert "aggressive" in script.lower() or "流氓" in script or "pct" in script
        assert "memory.total" in script


# ══════════════════════════════════════════════
# Calibration ratio
# ══════════════════════════════════════════════

class TestComputeCalibrationRatio:
    def test_empty_timings(self):
        assert _compute_calibration_ratio({}) == 1.0

    def test_single_timing(self):
        timings = {"a": {"planned_min": 30, "actual_min": 21}}
        ratio = _compute_calibration_ratio(timings)
        assert ratio == pytest.approx(0.7)

    def test_multiple_timings_median_odd(self):
        timings = {
            "a": {"planned_min": 30, "actual_min": 21},   # 0.7
            "b": {"planned_min": 60, "actual_min": 30},   # 0.5
            "c": {"planned_min": 20, "actual_min": 20},   # 1.0
        }
        # sorted: [0.5, 0.7, 1.0] → median = 0.7
        assert _compute_calibration_ratio(timings) == pytest.approx(0.7)

    def test_multiple_timings_median_even(self):
        timings = {
            "a": {"planned_min": 10, "actual_min": 5},    # 0.5
            "b": {"planned_min": 10, "actual_min": 8},    # 0.8
            "c": {"planned_min": 10, "actual_min": 10},   # 1.0
            "d": {"planned_min": 10, "actual_min": 12},   # 1.2
        }
        # sorted: [0.5, 0.8, 1.0, 1.2] → median = (0.8 + 1.0) / 2 = 0.9
        assert _compute_calibration_ratio(timings) == pytest.approx(0.9)

    def test_skips_zero_planned(self):
        timings = {
            "a": {"planned_min": 0, "actual_min": 10},
            "b": {"planned_min": 30, "actual_min": 21},  # 0.7
        }
        assert _compute_calibration_ratio(timings) == pytest.approx(0.7)

    def test_skips_zero_actual(self):
        timings = {
            "a": {"planned_min": 30, "actual_min": 0},
            "b": {"planned_min": 20, "actual_min": 30},  # 1.5
        }
        assert _compute_calibration_ratio(timings) == pytest.approx(1.5)

    def test_skips_missing_fields(self):
        timings = {
            "a": {"planned_min": 30},                     # missing actual
            "b": {"actual_min": 10},                      # missing planned
            "c": {"planned_min": 20, "actual_min": 10},   # 0.5
        }
        assert _compute_calibration_ratio(timings) == pytest.approx(0.5)

    def test_all_invalid_returns_default(self):
        timings = {
            "a": {"planned_min": 0, "actual_min": 0},
            "b": {},
        }
        assert _compute_calibration_ratio(timings) == 1.0


class TestEstimateBatchMinutesWithCalibration:
    def test_calibrated_estimate(self):
        tasks = [
            {"id": "a", "estimated_minutes": 60},
            {"id": "b", "estimated_minutes": 30},
        ]
        batch = [
            {"task_ids": ["a"], "gpu_ids": [0]},
            {"task_ids": ["b"], "gpu_ids": [1]},
        ]
        # ratio 0.5 → a: 60*0.5=30, b: 30*0.5=15, max=30
        timings = {"x": {"planned_min": 10, "actual_min": 5}}
        assert estimate_batch_minutes(batch, tasks, timings=timings) == 30

    def test_uses_actual_for_rerun_task(self):
        """If a task has actual timing data, use that instead of calibrated estimate."""
        tasks = [{"id": "a", "estimated_minutes": 60}]
        batch = [{"task_ids": ["a"], "gpu_ids": [0]}]
        timings = {"a": {"planned_min": 60, "actual_min": 22}}
        assert estimate_batch_minutes(batch, tasks, timings=timings) == 22

    def test_no_timings_no_calibration(self):
        tasks = [{"id": "a", "estimated_minutes": 60}]
        batch = [{"task_ids": ["a"], "gpu_ids": [0]}]
        assert estimate_batch_minutes(batch, tasks, timings=None) == 60

    def test_calibration_with_ratio_gt_1(self):
        """Tasks taking longer than planned → ratio > 1."""
        tasks = [{"id": "a", "estimated_minutes": 30}]
        batch = [{"task_ids": ["a"], "gpu_ids": [0]}]
        timings = {"x": {"planned_min": 10, "actual_min": 15}}  # ratio 1.5
        assert estimate_batch_minutes(batch, tasks, timings=timings) == 45  # 30 * 1.5


class TestGetBatchInfoCalibration:
    def test_no_timings_ratio_1(self, tmp_path):
        plan_dir = tmp_path / "plan"
        plan_dir.mkdir()
        tasks = [{"id": "a", "depends_on": [], "estimated_minutes": 30}]
        (plan_dir / "task_plan.json").write_text(json.dumps({"tasks": tasks}))

        info = get_batch_info(tmp_path, [0])
        assert info["calibration_ratio"] == 1.0
        assert info["calibrated"] is False

    def test_with_timings_returns_ratio(self, tmp_path):
        plan_dir = tmp_path / "plan"
        plan_dir.mkdir()
        tasks = [
            {"id": "a", "depends_on": [], "estimated_minutes": 30},
            {"id": "b", "depends_on": ["a"], "estimated_minutes": 60},
        ]
        (plan_dir / "task_plan.json").write_text(json.dumps({"tasks": tasks}))
        exp_dir = tmp_path / "exp"
        exp_dir.mkdir()
        (exp_dir / "gpu_progress.json").write_text(json.dumps({
            "completed": ["a"], "failed": [],
            "timings": {
                "a": {"planned_min": 30, "actual_min": 21}
            }
        }))

        info = get_batch_info(tmp_path, [0])
        assert info["calibration_ratio"] == 0.7
        assert info["calibrated"] is True
        # b estimated 60 * 0.7 = 42
        assert info["estimated_minutes"] == 42


# ══════════════════════════════════════════════
# Experiment monitor
# ══════════════════════════════════════════════

class TestExperimentMonitorScript:
    def test_generates_bash_script(self):
        script = experiment_monitor_script(
            ssh_server="gpu-server",
            remote_project_dir="/home/user/sibyl/projects/test",
            task_ids=["task_1a", "task_2a"],
        )
        assert "#!/bin/bash" in script
        assert "gpu-server" in script
        assert "task_1a" in script
        assert "task_2a" in script
        assert "DONE" in script
        assert "exp/results" in script

    def test_timeout_included(self):
        script = experiment_monitor_script(
            ssh_server="host",
            remote_project_dir="/path",
            task_ids=["a"],
            timeout_minutes=60,
        )
        assert "Timeout" in script or "timeout" in script
        assert "3600" in script  # 60 * 60

    def test_no_timeout_by_default(self):
        script = experiment_monitor_script(
            ssh_server="host",
            remote_project_dir="/path",
            task_ids=["a"],
            timeout_minutes=0,
        )
        assert "unlimited" in script

    def test_custom_marker_file(self):
        script = experiment_monitor_script(
            ssh_server="host",
            remote_project_dir="/path",
            task_ids=["a"],
            marker_file="/custom/marker.json",
        )
        assert "/custom/marker.json" in script

    def test_single_task(self):
        script = experiment_monitor_script(
            ssh_server="host",
            remote_project_dir="/path",
            task_ids=["only_one"],
        )
        assert "only_one" in script
        assert "TOTAL=1" in script


class TestReadMonitorResult:
    def test_file_not_found(self, tmp_path):
        result = read_monitor_result(str(tmp_path / "nonexistent.json"))
        assert result is None

    def test_reads_monitoring_status(self, tmp_path):
        marker = tmp_path / "monitor.json"
        marker.write_text(json.dumps({
            "status": "monitoring",
            "completed": ["task_1a"],
            "pending": ["task_2a"],
            "elapsed_sec": 300,
        }))
        result = read_monitor_result(str(marker))
        assert result["status"] == "monitoring"
        assert result["completed"] == ["task_1a"]

    def test_reads_all_complete(self, tmp_path):
        marker = tmp_path / "monitor.json"
        marker.write_text(json.dumps({
            "status": "all_complete",
            "completed": ["task_1a", "task_2a"],
            "pending": [],
            "elapsed_sec": 600,
        }))
        result = read_monitor_result(str(marker))
        assert result["status"] == "all_complete"

    def test_corrupt_json(self, tmp_path):
        marker = tmp_path / "monitor.json"
        marker.write_text("not json")
        result = read_monitor_result(str(marker))
        assert result is None


# ══════════════════════════════════════════════
# Running task tracking
# ══════════════════════════════════════════════

class TestRegisterRunningTasks:
    def test_register_new_tasks(self, tmp_path):
        register_running_tasks(tmp_path, {"task_a": [0, 1], "task_b": [2]})
        progress = json.loads((tmp_path / "exp" / "gpu_progress.json").read_text())
        assert "task_a" in progress["running"]
        assert progress["running"]["task_a"]["gpu_ids"] == [0, 1]
        assert "task_b" in progress["running"]
        assert progress["running"]["task_b"]["gpu_ids"] == [2]
        assert "started_at" in progress["running"]["task_a"]

    def test_register_preserves_existing(self, tmp_path):
        (tmp_path / "exp").mkdir(parents=True)
        (tmp_path / "exp" / "gpu_progress.json").write_text(json.dumps({
            "completed": ["task_0"], "failed": [], "running": {},
            "timings": {"task_0": {"planned_min": 10, "actual_min": 8}},
        }))
        register_running_tasks(tmp_path, {"task_a": [0]})
        progress = json.loads((tmp_path / "exp" / "gpu_progress.json").read_text())
        assert "task_0" in progress["completed"]
        assert "task_a" in progress["running"]
        assert progress["timings"]["task_0"]["actual_min"] == 8

    def test_register_append_to_existing_running(self, tmp_path):
        (tmp_path / "exp").mkdir(parents=True)
        (tmp_path / "exp" / "gpu_progress.json").write_text(json.dumps({
            "completed": [], "failed": [], "running": {
                "task_a": {"gpu_ids": [0], "started_at": "2026-01-01T00:00:00"},
            }, "timings": {},
        }))
        register_running_tasks(tmp_path, {"task_b": [1]})
        progress = json.loads((tmp_path / "exp" / "gpu_progress.json").read_text())
        assert "task_a" in progress["running"]
        assert "task_b" in progress["running"]


class TestUnregisterRunningTask:
    def test_unregister_removes_task(self, tmp_path):
        (tmp_path / "exp").mkdir(parents=True)
        (tmp_path / "exp" / "gpu_progress.json").write_text(json.dumps({
            "completed": [], "failed": [],
            "running": {
                "task_a": {"gpu_ids": [0], "started_at": "2026-01-01"},
                "task_b": {"gpu_ids": [1], "started_at": "2026-01-01"},
            },
            "timings": {},
        }))
        unregister_running_task(tmp_path, "task_a")
        progress = json.loads((tmp_path / "exp" / "gpu_progress.json").read_text())
        assert "task_a" not in progress["running"]
        assert "task_b" in progress["running"]

    def test_unregister_nonexistent_is_noop(self, tmp_path):
        (tmp_path / "exp").mkdir(parents=True)
        (tmp_path / "exp" / "gpu_progress.json").write_text(json.dumps({
            "completed": [], "failed": [], "running": {}, "timings": {},
        }))
        unregister_running_task(tmp_path, "nonexistent")  # should not crash

    def test_unregister_no_file_is_noop(self, tmp_path):
        unregister_running_task(tmp_path, "task_a")  # should not crash


class TestGetRunningGpuIds:
    def test_returns_occupied_gpus(self, tmp_path):
        (tmp_path / "exp").mkdir(parents=True)
        (tmp_path / "exp" / "gpu_progress.json").write_text(json.dumps({
            "completed": [], "failed": [],
            "running": {
                "task_a": {"gpu_ids": [0, 1], "started_at": "2026-01-01"},
                "task_b": {"gpu_ids": [3], "started_at": "2026-01-01"},
            },
            "timings": {},
        }))
        occupied = get_running_gpu_ids(tmp_path)
        assert occupied == [0, 1, 3]

    def test_no_running_returns_empty(self, tmp_path):
        assert get_running_gpu_ids(tmp_path) == []


class TestGetNextBatchWithRunning:
    """Test that get_next_batch excludes running tasks."""

    def _write_plan(self, ws, tasks):
        (ws / "plan").mkdir(parents=True, exist_ok=True)
        (ws / "plan" / "task_plan.json").write_text(json.dumps({"tasks": tasks}))

    def _write_progress(self, ws, completed=None, running=None):
        (ws / "exp").mkdir(parents=True, exist_ok=True)
        (ws / "exp" / "gpu_progress.json").write_text(json.dumps({
            "completed": completed or [],
            "failed": [],
            "running": running or {},
            "timings": {},
        }))

    def test_excludes_running_tasks(self, tmp_path):
        tasks = [
            {"id": "a", "depends_on": [], "gpu_count": 1, "estimated_minutes": 10},
            {"id": "b", "depends_on": [], "gpu_count": 1, "estimated_minutes": 10},
            {"id": "c", "depends_on": [], "gpu_count": 1, "estimated_minutes": 10},
        ]
        self._write_plan(tmp_path, tasks)
        self._write_progress(tmp_path, running={
            "a": {"gpu_ids": [0], "started_at": "2026-01-01"},
        })
        batch = get_next_batch(tmp_path, [1, 2])
        task_ids = [a["task_ids"][0] for a in batch]
        assert "a" not in task_ids
        assert "b" in task_ids
        assert "c" in task_ids

    def test_all_running_returns_empty(self, tmp_path):
        tasks = [
            {"id": "a", "depends_on": [], "gpu_count": 1, "estimated_minutes": 10},
        ]
        self._write_plan(tmp_path, tasks)
        self._write_progress(tmp_path, running={
            "a": {"gpu_ids": [0], "started_at": "2026-01-01"},
        })
        batch = get_next_batch(tmp_path, [1])
        assert batch == []  # running but not completed

    def test_completed_and_running_both_excluded(self, tmp_path):
        tasks = [
            {"id": "a", "depends_on": [], "gpu_count": 1, "estimated_minutes": 10},
            {"id": "b", "depends_on": [], "gpu_count": 1, "estimated_minutes": 10},
            {"id": "c", "depends_on": ["a"], "gpu_count": 1, "estimated_minutes": 10},
        ]
        self._write_plan(tmp_path, tasks)
        self._write_progress(
            tmp_path,
            completed=["a"],
            running={"b": {"gpu_ids": [0], "started_at": "2026-01-01"}},
        )
        batch = get_next_batch(tmp_path, [1])
        # c depends on a (completed) → ready; b is running → excluded
        task_ids = [a["task_ids"][0] for a in batch]
        assert task_ids == ["c"]

    def test_dependency_on_running_task_blocked(self, tmp_path):
        tasks = [
            {"id": "a", "depends_on": [], "gpu_count": 1, "estimated_minutes": 10},
            {"id": "b", "depends_on": ["a"], "gpu_count": 1, "estimated_minutes": 10},
        ]
        self._write_plan(tmp_path, tasks)
        self._write_progress(tmp_path, running={
            "a": {"gpu_ids": [0], "started_at": "2026-01-01"},
        })
        batch = get_next_batch(tmp_path, [1])
        # b depends on a which is running (not completed) → b is blocked
        assert batch == []


class TestMonitorScriptDispatchNeeded:
    """Test that experiment_monitor_script includes dispatch_needed field."""

    def test_script_includes_dispatch_logic(self):
        script = experiment_monitor_script(
            ssh_server="test-server",
            remote_project_dir="/tmp/test",
            task_ids=["t1", "t2"],
        )
        assert "dispatch_needed" in script
        assert "PREV_DONE_COUNT" in script
        assert "DISPATCH" in script
