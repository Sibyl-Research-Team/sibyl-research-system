"""Structured error collection for Sibyl self-healing system.

Collects errors with full context (traceback, stage, project) into
a structured JSONL file for the self-heal router to process.
"""

import hashlib
import json
import time
import traceback as tb_module
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable


def _compute_error_id(error_type: str, message: str, file_path: str | None) -> str:
    """Deterministic hash from error type + message + file."""
    key = f"{error_type}:{message}:{file_path or ''}"
    return hashlib.sha256(key.encode()).hexdigest()[:12]


def categorize_exception(exc: BaseException) -> str:
    """Map an exception to a self-heal category."""
    if isinstance(exc, (ImportError, ModuleNotFoundError)):
        return "import"
    if isinstance(exc, TypeError):
        return "type"
    # json.JSONDecodeError is a subclass of ValueError, so check it first
    if isinstance(exc, (json.JSONDecodeError, FileNotFoundError, UnicodeDecodeError)):
        return "config"
    if isinstance(exc, (ValueError, KeyError, IndexError, AttributeError)):
        return "state"
    if isinstance(exc, OSError):
        return "build"
    return "state"


@dataclass
class StructuredError:
    """A structured error record for self-healing processing."""

    error_type: str
    category: str  # "import" | "test" | "type" | "state" | "config" | "build" | "prompt"
    message: str
    traceback: str
    file_path: str | None = None
    line_number: int | None = None
    stage: str | None = None
    project: str | None = None
    timestamp: float = field(default_factory=time.time)
    context: dict = field(default_factory=dict)
    processed: bool = False

    # Internal: allow tests to override error_id
    _override_id: str | None = field(default=None, repr=False)

    @property
    def error_id(self) -> str:
        if self._override_id:
            return self._override_id
        return _compute_error_id(self.error_type, self.message, self.file_path)

    def to_dict(self) -> dict:
        return {
            "error_id": self.error_id,
            "error_type": self.error_type,
            "category": self.category,
            "message": self.message,
            "traceback": self.traceback,
            "file_path": self.file_path,
            "line_number": self.line_number,
            "stage": self.stage,
            "project": self.project,
            "timestamp": self.timestamp,
            "context": self.context,
            "processed": self.processed,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "StructuredError":
        return cls(
            error_type=data["error_type"],
            category=data["category"],
            message=data["message"],
            traceback=data.get("traceback", ""),
            file_path=data.get("file_path"),
            line_number=data.get("line_number"),
            stage=data.get("stage"),
            project=data.get("project"),
            timestamp=data.get("timestamp", 0.0),
            context=data.get("context", {}),
            processed=data.get("processed", False),
        )


class ErrorCollector:
    """Collects structured errors into a JSONL file."""

    def __init__(self, errors_file: Path):
        self.errors_file = errors_file

    def collect(self, error: StructuredError):
        """Append a structured error to the JSONL file."""
        self.errors_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.errors_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(error.to_dict(), ensure_ascii=False) + "\n")

    def collect_exception(
        self,
        exc: BaseException,
        stage: str | None = None,
        project: str | None = None,
        context: dict | None = None,
    ):
        """Collect an exception as a structured error."""
        tb_str = "".join(tb_module.format_exception(type(exc), exc, exc.__traceback__))
        # Extract file/line from traceback
        file_path = None
        line_number = None
        if exc.__traceback__:
            frame = exc.__traceback__
            while frame.tb_next:
                frame = frame.tb_next
            file_path = frame.tb_frame.f_code.co_filename
            line_number = frame.tb_lineno

        error = StructuredError(
            error_type=type(exc).__name__,
            category=categorize_exception(exc),
            message=str(exc),
            traceback=tb_str,
            file_path=file_path,
            line_number=line_number,
            stage=stage,
            project=project,
            context=context or {},
        )
        self.collect(error)

    def read_errors(self, unprocessed_only: bool = True) -> list[StructuredError]:
        """Read all errors from the JSONL file."""
        if not self.errors_file.exists():
            return []
        errors = []
        for line in self.errors_file.read_text(encoding="utf-8").strip().split("\n"):
            if not line.strip():
                continue
            try:
                data = json.loads(line)
                err = StructuredError.from_dict(data)
                if unprocessed_only and err.processed:
                    continue
                errors.append(err)
            except (json.JSONDecodeError, KeyError):
                continue
        return errors

    def mark_processed(self, error_id: str):
        """Mark an error as processed by rewriting the JSONL file."""
        if not self.errors_file.exists():
            return
        lines = self.errors_file.read_text(encoding="utf-8").strip().split("\n")
        updated = []
        for line in lines:
            if not line.strip():
                continue
            try:
                data = json.loads(line)
                if data.get("error_id") == error_id:
                    data["processed"] = True
                updated.append(json.dumps(data, ensure_ascii=False))
            except json.JSONDecodeError:
                updated.append(line)
        self.errors_file.write_text("\n".join(updated) + "\n", encoding="utf-8")


def wrap_cli(collector: ErrorCollector) -> Callable:
    """Decorator factory: wrap CLI functions to catch and collect errors."""

    def decorator(func: Callable) -> Callable:
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as exc:
                collector.collect_exception(exc)
                return {
                    "error": True,
                    "message": str(exc),
                    "error_type": type(exc).__name__,
                }

        wrapper.__name__ = func.__name__
        wrapper.__doc__ = func.__doc__
        return wrapper

    return decorator
