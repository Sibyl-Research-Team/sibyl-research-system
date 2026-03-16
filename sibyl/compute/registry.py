"""Compute backend factory."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sibyl.compute.base import ComputeBackend

if TYPE_CHECKING:
    from sibyl.config import Config


def get_backend(config: "Config", workspace_active_root: str = "") -> ComputeBackend:
    """Return the appropriate compute backend for *config*.

    Args:
        config: Sibyl project configuration.
        workspace_active_root: Local workspace active root path.  Required
            for the ``"local"`` backend to know where experiment files live.

    Returns:
        A :class:`ComputeBackend` instance.

    Raises:
        ValueError: If ``config.compute_backend`` is not recognised.
    """
    backend_type = config.compute_backend

    if backend_type == "local":
        from sibyl.compute.local_backend import LocalBackend
        return LocalBackend.from_config(config, workspace_active_root)

    if backend_type == "ssh":
        from sibyl.compute.ssh_backend import SSHBackend
        return SSHBackend.from_config(config, workspace_active_root)

    raise ValueError(
        f"Unknown compute_backend {backend_type!r}, "
        f"must be one of {{\"local\", \"ssh\"}}"
    )
