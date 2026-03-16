"""Tests for sibyl.auto_fix module."""

import json
from pathlib import Path

import pytest

from sibyl.auto_fix import attempt_auto_fix, _fix_missing_dir, _fix_config


class TestAttemptAutoFix:
    def test_unknown_error_returns_none(self, tmp_path):
        error = {"error_type": "unknown_error", "message": "something weird"}
        assert attempt_auto_fix(error, tmp_path) is None

    def test_empty_error_returns_none(self, tmp_path):
        assert attempt_auto_fix({}, tmp_path) is None


class TestFixMissingDir:
    def test_creates_missing_directory(self, tmp_path):
        missing_dir = tmp_path / "subdir" / "nested"
        error = {
            "error_type": "FileNotFoundError",
            "message": f"No such file or directory: '{missing_dir}'",
        }
        result = _fix_missing_dir(error, tmp_path, error["message"])
        assert result is not None
        assert result["fixed"] is True
        assert result["action"] == "mkdir"
        assert missing_dir.exists()

    def test_creates_parent_for_file_path(self, tmp_path):
        file_path = tmp_path / "logs" / "output.txt"
        error = {
            "error_type": "FileNotFoundError",
            "message": f"No such file or directory: '{file_path}'",
        }
        result = _fix_missing_dir(error, tmp_path, error["message"])
        assert result is not None
        assert result["fixed"] is True
        assert file_path.parent.exists()

    def test_refuses_outside_workspace(self, tmp_path):
        error = {
            "error_type": "FileNotFoundError",
            "message": "No such file or directory: '/etc/evil'",
        }
        result = _fix_missing_dir(error, tmp_path, error["message"])
        assert result is None

    def test_no_path_in_error(self, tmp_path):
        error = {
            "error_type": "FileNotFoundError",
            "message": "Something went wrong",
        }
        result = _fix_missing_dir(error, tmp_path, error["message"])
        assert result is None


class TestFixConfig:
    def test_reformats_json(self, tmp_path):
        config_file = tmp_path / "config.json"
        config_file.write_text('{"key":"value","num":42}')
        error = {
            "error_type": "config",
            "message": f"error parsing '{config_file}'",
        }
        result = _fix_config(error, tmp_path, error["message"])
        assert result is not None
        assert result["fixed"] is True
        # Verify it was reformatted with indentation
        content = config_file.read_text()
        assert "  " in content  # indented

    def test_reformats_yaml(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text("key: value\nlist: [1, 2, 3]")
        error = {
            "error_type": "config",
            "message": f"error loading '{config_file}'",
        }
        result = _fix_config(error, tmp_path, error["message"])
        assert result is not None
        assert result["fixed"] is True

    def test_no_config_file_found(self, tmp_path):
        error = {
            "error_type": "config",
            "message": "generic error with no file path",
        }
        result = _fix_config(error, tmp_path, error["message"])
        assert result is None


class TestIntegrationWithSelfHealScan:
    """Test that auto_fix integrates properly with the self-heal scan."""

    def test_auto_fix_import_path(self, tmp_path):
        """Verify attempt_auto_fix handles import errors."""
        error = {
            "error_type": "ImportError",
            "message": "No module named 'nonexistent_module_xyz_123'",
            "traceback": "",
        }
        # This should return None because nonexistent_module_xyz_123 is not
        # in the safe_packages list and pip install would fail
        result = attempt_auto_fix(error, tmp_path)
        # Either None (not in safe list) or a failed install
        # The important thing is it doesn't crash
        assert result is None or isinstance(result, dict)

    def test_file_not_found_auto_fix(self, tmp_path):
        """Verify FileNotFoundError triggers mkdir fix."""
        missing = tmp_path / "experiment" / "results"
        error = {
            "error_type": "FileNotFoundError",
            "message": f"FileNotFoundError: [Errno 2] No such file or directory: '{missing}'",
            "traceback": "",
        }
        result = attempt_auto_fix(error, tmp_path)
        assert result is not None
        assert result["fixed"] is True
        assert missing.exists()
