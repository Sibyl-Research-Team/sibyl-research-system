"""Tests for Sibyl self-healing system (error collector + router)."""

import json
import time

import pytest

from sibyl.error_collector import StructuredError, ErrorCollector, wrap_cli, categorize_exception
from sibyl.self_heal import (
    SelfHealRouter,
    SKILL_ROUTE_TABLE,
    CIRCUIT_BREAKER_MAX,
    MAX_FILES_PER_FIX,
    PROTECTED_FILES,
)


# ══════════════════════════════════════════════
# Phase 1: Error Collector tests
# ══════════════════════════════════════════════


class TestStructuredError:
    def test_creation(self):
        err = StructuredError(
            error_type="ImportError",
            category="import",
            message="No module named 'foo'",
            traceback="Traceback ...",
            file_path="sibyl/orchestrate.py",
            line_number=42,
            stage="literature_search",
            project="test-proj",
            context={},
        )
        assert err.error_type == "ImportError"
        assert err.category == "import"
        assert err.error_id  # auto-generated hash
        assert err.timestamp > 0

    def test_error_id_deterministic(self):
        """Same error type + message + file should produce same error_id."""
        err1 = StructuredError(
            error_type="ImportError",
            category="import",
            message="No module named 'foo'",
            traceback="tb1",
            file_path="sibyl/orchestrate.py",
            line_number=42,
        )
        err2 = StructuredError(
            error_type="ImportError",
            category="import",
            message="No module named 'foo'",
            traceback="tb2",  # different traceback
            file_path="sibyl/orchestrate.py",
            line_number=99,  # different line
        )
        assert err1.error_id == err2.error_id

    def test_error_id_differs_for_different_errors(self):
        err1 = StructuredError(
            error_type="ImportError",
            category="import",
            message="No module named 'foo'",
            traceback="",
            file_path="a.py",
        )
        err2 = StructuredError(
            error_type="ImportError",
            category="import",
            message="No module named 'bar'",
            traceback="",
            file_path="a.py",
        )
        assert err1.error_id != err2.error_id

    def test_to_dict(self):
        err = StructuredError(
            error_type="ValueError",
            category="state",
            message="bad value",
            traceback="",
        )
        d = err.to_dict()
        assert d["error_type"] == "ValueError"
        assert "error_id" in d
        assert "timestamp" in d


class TestCategorizeException:
    def test_import_error(self):
        assert categorize_exception(ImportError("no module")) == "import"

    def test_module_not_found(self):
        assert categorize_exception(ModuleNotFoundError("no module")) == "import"

    def test_type_error(self):
        assert categorize_exception(TypeError("bad type")) == "type"

    def test_value_error(self):
        assert categorize_exception(ValueError("bad value")) == "state"

    def test_key_error(self):
        assert categorize_exception(KeyError("missing")) == "state"

    def test_json_decode_error(self):
        try:
            json.loads("{bad}")
        except json.JSONDecodeError as e:
            assert categorize_exception(e) == "config"

    def test_file_not_found(self):
        assert categorize_exception(FileNotFoundError("missing")) == "config"

    def test_os_error(self):
        assert categorize_exception(OSError("disk full")) == "build"

    def test_generic_exception(self):
        assert categorize_exception(Exception("unknown")) == "state"


class TestErrorCollector:
    def test_collect_writes_jsonl(self, tmp_path):
        errors_file = tmp_path / "errors.jsonl"
        collector = ErrorCollector(errors_file)
        err = StructuredError(
            error_type="ImportError",
            category="import",
            message="No module named 'foo'",
            traceback="Traceback ...",
        )
        collector.collect(err)
        lines = errors_file.read_text().strip().split("\n")
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["error_type"] == "ImportError"
        assert data["category"] == "import"

    def test_collect_appends(self, tmp_path):
        errors_file = tmp_path / "errors.jsonl"
        collector = ErrorCollector(errors_file)
        for i in range(3):
            collector.collect(StructuredError(
                error_type="ValueError",
                category="state",
                message=f"error {i}",
                traceback="",
            ))
        lines = errors_file.read_text().strip().split("\n")
        assert len(lines) == 3

    def test_collect_from_exception(self, tmp_path):
        errors_file = tmp_path / "errors.jsonl"
        collector = ErrorCollector(errors_file)
        try:
            raise ImportError("No module named 'yaml'")
        except ImportError as e:
            collector.collect_exception(e, stage="init", project="test")

        lines = errors_file.read_text().strip().split("\n")
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["category"] == "import"
        assert data["stage"] == "init"
        assert data["project"] == "test"

    def test_read_errors(self, tmp_path):
        errors_file = tmp_path / "errors.jsonl"
        collector = ErrorCollector(errors_file)
        collector.collect(StructuredError(
            error_type="ImportError",
            category="import",
            message="test",
            traceback="",
        ))
        errors = collector.read_errors()
        assert len(errors) == 1
        assert errors[0].error_type == "ImportError"

    def test_read_errors_empty(self, tmp_path):
        errors_file = tmp_path / "errors.jsonl"
        collector = ErrorCollector(errors_file)
        assert collector.read_errors() == []

    def test_mark_processed(self, tmp_path):
        errors_file = tmp_path / "errors.jsonl"
        collector = ErrorCollector(errors_file)
        err = StructuredError(
            error_type="ImportError",
            category="import",
            message="test",
            traceback="",
        )
        collector.collect(err)
        collector.mark_processed(err.error_id)

        unprocessed = collector.read_errors(unprocessed_only=True)
        assert len(unprocessed) == 0

        all_errors = collector.read_errors(unprocessed_only=False)
        assert len(all_errors) == 1


class TestWrapCli:
    def test_wraps_successful_function(self, tmp_path):
        errors_file = tmp_path / "errors.jsonl"
        collector = ErrorCollector(errors_file)

        @wrap_cli(collector)
        def my_func():
            return {"result": "ok"}

        result = my_func()
        assert result == {"result": "ok"}
        assert not errors_file.exists()

    def test_wraps_failing_function(self, tmp_path):
        errors_file = tmp_path / "errors.jsonl"
        collector = ErrorCollector(errors_file)

        @wrap_cli(collector)
        def my_func():
            raise ValueError("test error")

        result = my_func()
        assert result["error"] is True
        assert "test error" in result["message"]

        lines = errors_file.read_text().strip().split("\n")
        assert len(lines) == 1


# ══════════════════════════════════════════════
# Phase 2: Self-Heal Router tests
# ══════════════════════════════════════════════


class TestSelfHealRouter:
    def _make_error(self, category="import", message="test", error_id=None):
        err = StructuredError(
            error_type="ImportError",
            category=category,
            message=message,
            traceback="",
        )
        if error_id:
            err._override_id = error_id
        return err

    def test_route_to_skills(self):
        router = SelfHealRouter.__new__(SelfHealRouter)
        router._state = {"pending": [], "in_progress": {}, "fixed": {}, "circuit_broken": {}}
        skills = router.route_to_skills(self._make_error("import"))
        assert "python-patterns" in skills
        assert "tdd-workflow" in skills

    def test_route_test_failure(self):
        router = SelfHealRouter.__new__(SelfHealRouter)
        router._state = {"pending": [], "in_progress": {}, "fixed": {}, "circuit_broken": {}}
        skills = router.route_to_skills(self._make_error("test"))
        assert "systematic-debugging" in skills

    def test_route_unknown_category(self):
        router = SelfHealRouter.__new__(SelfHealRouter)
        router._state = {"pending": [], "in_progress": {}, "fixed": {}, "circuit_broken": {}}
        skills = router.route_to_skills(self._make_error("unknown_cat"))
        assert "systematic-debugging" in skills  # fallback

    def test_deduplicate(self, tmp_path):
        state_file = tmp_path / "state.json"
        router = SelfHealRouter(state_file)
        errors = [
            self._make_error("import", "same error"),
            self._make_error("import", "same error"),
            self._make_error("import", "different error"),
        ]
        deduped = router.deduplicate(errors)
        assert len(deduped) == 2

    def test_prioritize(self, tmp_path):
        state_file = tmp_path / "state.json"
        router = SelfHealRouter(state_file)
        errors = [
            self._make_error("config"),
            self._make_error("import"),
            self._make_error("build"),
        ]
        prioritized = router.prioritize(errors)
        categories = [e.category for e in prioritized]
        # import and build should be before config
        assert categories.index("import") < categories.index("config")

    def test_circuit_breaker_not_triggered(self, tmp_path):
        state_file = tmp_path / "state.json"
        router = SelfHealRouter(state_file)
        err = self._make_error("import", "test")
        assert router.check_circuit_breaker(err.error_id) is False

    def test_circuit_breaker_triggers_after_max(self, tmp_path):
        state_file = tmp_path / "state.json"
        router = SelfHealRouter(state_file)
        err = self._make_error("import", "test")
        for _ in range(CIRCUIT_BREAKER_MAX):
            router.record_fix_attempt(err.error_id, success=False)
        assert router.check_circuit_breaker(err.error_id) is True

    def test_circuit_breaker_resets_on_success(self, tmp_path):
        state_file = tmp_path / "state.json"
        router = SelfHealRouter(state_file)
        err = self._make_error("import", "test")
        router.record_fix_attempt(err.error_id, success=False)
        router.record_fix_attempt(err.error_id, success=False)
        router.record_fix_attempt(err.error_id, success=True)
        assert router.check_circuit_breaker(err.error_id) is False

    def test_generate_repair_task(self, tmp_path):
        state_file = tmp_path / "state.json"
        router = SelfHealRouter(state_file)
        err = self._make_error("import", "No module named 'foo'")
        task = router.generate_repair_task(err)
        assert task["error_id"] == err.error_id
        assert task["category"] == "import"
        assert "skills" in task
        assert len(task["skills"]) > 0

    def test_record_fix_persists(self, tmp_path):
        state_file = tmp_path / "state.json"
        router = SelfHealRouter(state_file)
        err = self._make_error("import", "test")
        router.record_fix_attempt(err.error_id, success=True, commit_hash="abc123")

        # Reload from disk
        router2 = SelfHealRouter(state_file)
        assert err.error_id in router2._state["fixed"]
        assert router2._state["fixed"][err.error_id]["commit"] == "abc123"

    def test_protected_files_detection(self, tmp_path):
        state_file = tmp_path / "state.json"
        router = SelfHealRouter(state_file)
        err = self._make_error("state", "error in orchestrate")
        err.file_path = "sibyl/orchestrate.py"
        task = router.generate_repair_task(err)
        assert task["protected_file"] is True

    def test_status_report(self, tmp_path):
        state_file = tmp_path / "state.json"
        router = SelfHealRouter(state_file)
        err = self._make_error("import", "test")
        router.record_fix_attempt(err.error_id, success=True)
        status = router.get_status()
        assert "fixed" in status
        assert len(status["fixed"]) == 1

    def test_filter_already_fixed(self, tmp_path):
        state_file = tmp_path / "state.json"
        router = SelfHealRouter(state_file)
        err = self._make_error("import", "test")
        router.record_fix_attempt(err.error_id, success=True)
        filtered = router.filter_actionable([err])
        assert len(filtered) == 0

    def test_filter_circuit_broken(self, tmp_path):
        state_file = tmp_path / "state.json"
        router = SelfHealRouter(state_file)
        err = self._make_error("import", "test")
        for _ in range(CIRCUIT_BREAKER_MAX):
            router.record_fix_attempt(err.error_id, success=False)
        filtered = router.filter_actionable([err])
        assert len(filtered) == 0
