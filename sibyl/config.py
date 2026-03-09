import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
import yaml


@dataclass
class AgentConfig:
    """Reserved per-phase model config kept for backward compatibility.

    The current Claude Code runtime routes models through `.claude/agents`
    plus `model_tiers` / `agent_tier_map`. These nested blocks are parsed and
    persisted so older configs continue to load cleanly, but they are not the
    primary runtime control surface.
    """
    model: str = "claude-opus-4-6"
    max_tokens: int = 64000
    temperature: float = 0.7


@dataclass
class Config:
    workspaces_dir: Path = Path("workspaces")
    # Reserved compatibility blocks; current runtime model routing is controlled
    # by `.claude/agents` and model_tiers/agent_tier_map instead.
    ideation: AgentConfig = field(default_factory=lambda: AgentConfig(temperature=0.9))
    planning: AgentConfig = field(default_factory=AgentConfig)
    experiment: AgentConfig = field(default_factory=lambda: AgentConfig(temperature=0.3))
    writing: AgentConfig = field(default_factory=lambda: AgentConfig(temperature=0.5))
    max_parallel_tasks: int = 4
    idea_exp_cycles: int = 6
    experiment_timeout: int = 300
    review_enabled: bool = True

    # Language for user-facing / non-paper agent output ("en" or "zh")
    # Paper-writing artifacts remain English regardless of this setting.
    language: str = "zh"

    # GPU scheduling
    max_gpus: int = 4  # max GPUs to use (picks any free ones, not fixed IDs)
    gpus_per_task: int = 1
    ssh_server: str = "default"
    remote_base: str = "/home/user/sibyl_system"

    # GPU polling (for shared servers with other users)
    gpu_poll_enabled: bool = True
    gpu_free_threshold_mb: int = 2000  # GPU is "free" if memory < this
    gpu_poll_interval_sec: int = 600   # seconds between polls (10 min)
    gpu_poll_max_attempts: int = 0     # 0 = infinite (no timeout)

    # Aggressive GPU mode: treat GPUs with <25% VRAM usage as available
    # Useful on shared servers where GPUs are allocated but mostly idle
    gpu_aggressive_mode: bool = True
    gpu_aggressive_threshold_pct: int = 25  # VRAM usage % below which GPU is "available"

    # Pilot experiments
    pilot_samples: int = 16
    pilot_timeout: int = 600  # 10 min
    pilot_seeds: list[int] = field(default_factory=lambda: [42])

    # Full experiments
    full_seeds: list[int] = field(default_factory=lambda: [42, 123, 456])

    # Multi-agent debate
    debate_rounds: int = 2
    writing_revision_rounds: int = 2

    # Codex integration
    codex_enabled: bool = False
    codex_model: str = ""  # Codex model (empty = use default; ChatGPT accounts don't support custom models)

    # Writing mode
    writing_mode: str = "parallel"  # "sequential" | "parallel" | "codex"
    codex_writing_model: str = ""  # Codex writing model (empty = use default)

    # Experiment execution
    experiment_mode: str = "ssh_mcp"  # "ssh_mcp" | "server_codex" | "server_claude"
    server_codex_path: str = "codex"  # Codex CLI path on server
    server_claude_path: str = "claude"  # Claude CLI path on server

    # Remote environment
    remote_env_type: str = "conda"       # "conda" | "venv"
    remote_conda_path: str = ""          # empty = auto {remote_base}/miniconda3/bin/conda
    remote_conda_env_name: str = ""      # empty = auto sibyl_<project>; set to reuse an existing env
    iteration_dirs: bool = False         # True = iteration subdirectory mode

    # Lark sync
    lark_enabled: bool = True

    # Auto evolution
    evolution_enabled: bool = True

    # Self-healing
    self_heal_enabled: bool = True
    self_heal_interval_sec: int = 300   # scan interval (5 min)
    self_heal_max_attempts: int = 3     # circuit breaker threshold

    # Model routing
    model_tiers: dict = field(default_factory=lambda: {
        "heavy":    "claude-opus-4-6",
        "standard": "claude-opus-4-6",
        "light":    "claude-sonnet-4-6",
    })
    agent_tier_map: dict = field(default_factory=lambda: {
        # Heavy: deep reasoning
        "synthesizer": "heavy", "supervisor": "heavy",
        "supervisor_decision": "heavy", "editor": "heavy",
        "final_critic": "heavy", "critic": "heavy", "reflection": "heavy",
        # Standard: literature research (needs tool use + reasoning)
        "literature_researcher": "standard",
        # Light: simple evaluation
        "optimist": "light", "skeptic": "light", "strategist": "light",
        "section_critic": "light", "idea_critique": "light",
        # Everything else defaults to standard
    })

    @classmethod
    def from_yaml(cls, path: str) -> "Config":
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        cfg = cls()
        cfg.workspaces_dir = Path(data.get("workspaces_dir", "workspaces"))
        for agent_name in ["ideation", "planning", "experiment", "writing"]:
            if agent_name in data:
                setattr(cfg, agent_name, AgentConfig(**data[agent_name]))
        # Simple scalar fields
        for key in [
            "max_parallel_tasks", "experiment_timeout", "review_enabled",
            "ssh_server", "remote_base", "gpus_per_task", "max_gpus",
            "gpu_poll_enabled", "gpu_free_threshold_mb",
            "gpu_poll_interval_sec", "gpu_poll_max_attempts",
            "gpu_aggressive_mode", "gpu_aggressive_threshold_pct",
            "pilot_samples", "pilot_timeout",
            "debate_rounds", "writing_revision_rounds",
            "lark_enabled", "evolution_enabled",
            "idea_exp_cycles",
            "codex_enabled", "codex_model", "writing_mode", "codex_writing_model",
            "experiment_mode", "server_codex_path", "server_claude_path",
            "remote_env_type", "remote_conda_path", "remote_conda_env_name",
            "iteration_dirs",
            "language",
            "self_heal_enabled", "self_heal_interval_sec", "self_heal_max_attempts",
        ]:
            if key in data:
                setattr(cfg, key, data[key])
        # List fields
        for key in ["pilot_seeds", "full_seeds"]:
            if key in data:
                setattr(cfg, key, data[key])
        # Dict fields (model routing)
        for key in ["model_tiers", "agent_tier_map"]:
            if key in data:
                getattr(cfg, key).update(data[key])

        # Validate enum-like fields
        # Validate remote_env_type
        valid_env_types = {"conda", "venv"}
        if cfg.remote_env_type not in valid_env_types:
            raise ValueError(
                f"Invalid remote_env_type '{cfg.remote_env_type}', "
                f"must be one of {valid_env_types}"
            )

        valid_languages = {"zh", "en"}
        if cfg.language not in valid_languages:
            raise ValueError(
                f"Invalid language '{cfg.language}', "
                f"must be one of {valid_languages}"
            )

        valid_writing_modes = {"sequential", "parallel", "codex"}
        if cfg.writing_mode not in valid_writing_modes:
            raise ValueError(
                f"Invalid writing_mode '{cfg.writing_mode}', "
                f"must be one of {valid_writing_modes}"
            )
        valid_experiment_modes = {"ssh_mcp", "server_codex", "server_claude"}
        if cfg.experiment_mode not in valid_experiment_modes:
            raise ValueError(
                f"Invalid experiment_mode '{cfg.experiment_mode}', "
                f"must be one of {valid_experiment_modes}"
            )

        return cfg

    @classmethod
    def from_yaml_chain(cls, *paths: str) -> "Config":
        """Load config from multiple YAML files. Later files override earlier ones."""
        merged: dict = {}
        for path in paths:
            with open(path, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            for key, val in data.items():
                if isinstance(val, dict) and isinstance(merged.get(key), dict):
                    merged[key].update(val)
                else:
                    merged[key] = val
        # Write merged data to a temp structure and reuse from_yaml logic
        fd, tmp = tempfile.mkstemp(suffix=".yaml")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                yaml.dump(merged, f, allow_unicode=True)
            return cls.from_yaml(tmp)
        finally:
            os.unlink(tmp)

    def get_remote_env_cmd(self, project_name: str) -> str:
        """Return the environment activation command for remote execution."""
        if self.remote_env_type == "venv":
            return f"source {self.remote_base}/projects/{project_name}/.venv/bin/activate &&"
        conda = self.remote_conda_path or f"{self.remote_base}/miniconda3/bin/conda"
        env_name = self.remote_conda_env_name or f"sibyl_{project_name}"
        return f"{conda} run -n {env_name}"

    def to_dict(self) -> dict:
        """Serialize config for persisting into a project workspace."""
        data = asdict(self)
        data["workspaces_dir"] = str(self.workspaces_dir)
        return data

    def to_yaml(self) -> str:
        """Serialize config as YAML for workspace/config.yaml snapshots."""
        return yaml.safe_dump(self.to_dict(), allow_unicode=True, sort_keys=False)
