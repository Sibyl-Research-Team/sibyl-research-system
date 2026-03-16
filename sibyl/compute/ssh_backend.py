"""SSH compute backend — wraps existing gpu_scheduler and experiment_recovery functions."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sibyl.compute.base import ComputeBackend

if TYPE_CHECKING:
    from sibyl.config import Config


class SSHBackend(ComputeBackend):
    """Execute experiments on a remote GPU server via SSH."""

    def __init__(self, ssh_server: str, remote_base: str, config: "Config") -> None:
        self._ssh_server = ssh_server
        self._remote_base = remote_base
        self._config = config

    @property
    def backend_type(self) -> str:
        return "ssh"

    def project_dir(self, ws_name: str) -> str:
        return f"{self._remote_base}/projects/{ws_name}"

    def env_cmd(self, project_name: str) -> str:
        return self._config.get_remote_env_cmd(project_name)

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
        from sibyl.gpu_scheduler import gpu_poll_wait_script

        return gpu_poll_wait_script(
            ssh_server=self._ssh_server,
            candidate_gpu_ids=candidate_gpu_ids,
            threshold_mb=threshold_mb,
            poll_interval_sec=poll_interval_sec,
            max_polls=max_polls,
            marker_file=marker_file,
            aggressive_mode=aggressive_mode,
            aggressive_threshold_pct=aggressive_threshold_pct,
        )

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
        from sibyl.gpu_scheduler import experiment_monitor_script

        return experiment_monitor_script(
            ssh_server=self._ssh_server,
            remote_project_dir=project_dir,
            task_ids=task_ids,
            poll_interval_sec=poll_interval_sec,
            timeout_minutes=timeout_minutes,
            marker_file=marker_file,
            workspace_path=workspace_path,
            heartbeat_polls=heartbeat_polls,
            task_gpu_map=task_gpu_map,
        )

    @classmethod
    def from_config(cls, config: "Config", workspace_active_root: str = "") -> "SSHBackend":
        return cls(
            ssh_server=config.ssh_server,
            remote_base=config.remote_base,
            config=config,
        )
