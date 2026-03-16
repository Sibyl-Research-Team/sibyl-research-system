"""Abstract base class for compute backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sibyl.config import Config


class ComputeBackend(ABC):
    """Unified interface for GPU compute environments.

    Each backend encapsulates how to discover GPUs, run experiments,
    monitor task progress, and collect results.  The orchestrator calls
    backend methods instead of hardcoding SSH commands, making it trivial
    to add SLURM, Kubernetes, or other backends in the future.
    """

    @property
    @abstractmethod
    def backend_type(self) -> str:
        """Return the backend identifier (e.g. ``"local"``, ``"ssh"``)."""

    @abstractmethod
    def project_dir(self, ws_name: str) -> str:
        """Return the directory where experiment artifacts live.

        For SSH this is ``{remote_base}/projects/{ws_name}``.
        For local this is the workspace active root on the local filesystem.
        """

    @abstractmethod
    def env_cmd(self, project_name: str) -> str:
        """Return the shell command that activates the experiment environment.

        Examples: ``conda run -n sibyl_proj`` or
        ``source /path/.venv/bin/activate &&``.
        """

    @abstractmethod
    def gpu_poll_script(
        self,
        candidate_gpu_ids: list[int],
        threshold_mb: int,
        poll_interval_sec: int,
        max_polls: int,
        marker_file: str,
        aggressive_mode: bool,
        aggressive_threshold_pct: int,
    ) -> str:
        """Generate a bash script that polls for free GPUs.

        The script must:
        1. Run ``nvidia-smi`` to check GPU memory usage
        2. Write free GPU IDs to *marker_file* as JSON on success
        3. Exit 0 when free GPUs are found, exit 1 on timeout

        Returns a complete bash script string.
        """

    @abstractmethod
    def experiment_monitor_script(
        self,
        project_dir: str,
        task_ids: list[str],
        poll_interval_sec: int,
        timeout_minutes: int,
        marker_file: str,
        workspace_path: str,
        heartbeat_polls: int,
        task_gpu_map: dict[str, list[int]] | None,
    ) -> str:
        """Generate a bash daemon script that monitors running experiments.

        The script must:
        1. Check DONE / PID status for each task
        2. Refresh GPU state via ``nvidia-smi``
        3. Call ``cli dispatch`` when tasks complete (dynamic scheduling)
        4. Detect stuck processes
        5. Write wake events to the supervisor wake queue

        Returns a complete bash script string.
        """

    @classmethod
    @abstractmethod
    def from_config(cls, config: "Config", workspace_active_root: str) -> "ComputeBackend":
        """Construct a backend instance from a Config object."""
