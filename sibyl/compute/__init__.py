"""Pluggable compute backend abstraction for GPU experiment execution.

Provides a unified interface for GPU discovery, experiment monitoring,
and task execution across different compute environments (local, SSH,
and future backends like SLURM or Kubernetes).
"""

from sibyl.compute.base import ComputeBackend
from sibyl.compute.registry import get_backend

__all__ = ["ComputeBackend", "get_backend"]
