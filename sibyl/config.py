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
    idea_validation_rounds: int = 4
    max_iterations: int = 10
    max_iterations_cap: int = 100
    experiment_timeout: int = 300
    review_enabled: bool = True

    # Language for user-facing / non-paper agent output ("en" or "zh")
    # Paper-writing artifacts remain English regardless of this setting.
    language: str = "zh"

    # Compute backend: "local" (default) or "ssh"
    compute_backend: str = "local"

    # GPU scheduling
    max_gpus: int = 4  # max GPUs to use (picks any free ones, not fixed IDs)
    gpus_per_task: int = 1
    ssh_server: str = "default"
    remote_base: str = "/home/user/sibyl_system"  # remote GPU server path (compute_backend: ssh)

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
    pilot_samples: int = 100
    pilot_timeout: int = 900  # 15 min
    pilot_seeds: list[int] = field(default_factory=lambda: [42])

    # Full experiments
    full_seeds: list[int] = field(default_factory=lambda: [42, 123, 456])

    # Research focus (1=explore .. 5=deep_focus, default 3=balanced)
    # Controls how readily the system PIVOTs vs persists with the current idea.
    research_focus: int = 3

    # Multi-agent debate
    debate_rounds: int = 2
    writing_revision_rounds: int = 2

    # Codex integration
    codex_enabled: bool = False
    codex_model: str = ""  # Codex model (empty = use default; ChatGPT accounts don't support custom models)
    codex_idea_rounds: int = 2  # max Codex-guided idea refinement rounds (0 = no iteration)

    # Writing mode
    writing_mode: str = "parallel"  # "sequential" | "parallel" | "codex"
    codex_writing_model: str = ""  # Codex writing model (empty = use default)

    # Experiment execution
    experiment_mode: str = "ssh_mcp"  # "ssh_mcp" | "server_codex" | "server_claude"
    server_codex_path: str = "codex"  # Codex CLI path on server
    server_claude_path: str = "claude"  # Claude CLI path on server

    # Remote environment (compute_backend: ssh)
    remote_env_type: str = "conda"       # "conda" | "venv"
    remote_conda_path: str = ""          # empty = auto {remote_base}/miniconda3/bin/conda
    remote_conda_env_name: str = ""      # empty = auto sibyl_<project>; set to reuse an existing env
    iteration_dirs: bool = True          # True = iteration subdirectory mode (default)

    # Local environment (compute_backend: local)
    local_env_type: str = "conda"        # "conda" | "venv"
    local_conda_path: str = ""           # empty = system conda
    local_conda_env_name: str = ""       # empty = auto sibyl_<project>

    # Lark sync
    lark_enabled: bool = True

    # Auto evolution
    evolution_enabled: bool = True

    # Self-healing
    self_heal_enabled: bool = True
    self_heal_interval_sec: int = 300   # scan interval (5 min)
    self_heal_max_attempts: int = 3     # circuit breaker threshold

    # Experiment supervisor (Opus background subagent)
    # When False (default), experiment monitoring runs as a pure bash daemon
    # launched by the PostToolUse hook — zero LLM token cost.
    # When True, an Opus subagent is additionally started for anomaly
    # investigation (drift detection, stuck process diagnosis).
    supervisor_enabled: bool = False

    # Orchestra external skills integration
    orchestra_skills_enabled: bool = True
    orchestra_skills_dir: str = "~/.orchestra/skills"
    orchestra_skills_max: int = 15      # max skills injected per agent prompt

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

    @staticmethod
    def _resolve_local_path(raw_value: str, base_dir: Path) -> Path:
        path = Path(raw_value).expanduser()
        if not path.is_absolute():
            path = (base_dir / path).resolve()
        return path

    @classmethod
    def _from_data(cls, data: dict, *, base_dir: Path) -> "Config":
        cfg = cls()
        raw_workspaces_dir = str(data.get("workspaces_dir", cfg.workspaces_dir))
        cfg.workspaces_dir = cls._resolve_local_path(raw_workspaces_dir, base_dir)
        return cfg

    @classmethod
    def from_yaml(cls, path: str) -> "Config":
        config_path = Path(path).expanduser().resolve()
        with open(config_path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        cfg = cls._from_data(data, base_dir=config_path.parent)
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
            "research_focus",
            "debate_rounds", "writing_revision_rounds",
            "lark_enabled", "evolution_enabled",
            "idea_exp_cycles", "idea_validation_rounds",
            "max_iterations", "max_iterations_cap",
            "codex_enabled", "codex_model", "codex_idea_rounds",
            "writing_mode", "codex_writing_model",
            "compute_backend",
            "experiment_mode", "server_codex_path", "server_claude_path",
            "remote_env_type", "remote_conda_path", "remote_conda_env_name",
            "iteration_dirs",
            "local_env_type", "local_conda_path", "local_conda_env_name",
            "language",
            "self_heal_enabled", "self_heal_interval_sec", "self_heal_max_attempts",
            "supervisor_enabled",
            "orchestra_skills_enabled", "orchestra_skills_dir", "orchestra_skills_max",
        ]:
            if key in data:
                setattr(cfg, key, data[key])
        # List fields
        for key in ["pilot_seeds", "full_seeds"]:
            if key in data:
                setattr(cfg, key, data[key])
        if "orchestra_skills_dir" in data:
            cfg.orchestra_skills_dir = str(
                cls._resolve_local_path(str(data["orchestra_skills_dir"]), config_path.parent)
            )
        # Dict fields (model routing)
        for key in ["model_tiers", "agent_tier_map"]:
            if key in data:
                getattr(cfg, key).update(data[key])

        # Validate enum-like fields
        valid_compute_backends = {"local", "ssh"}
        if cfg.compute_backend not in valid_compute_backends:
            raise ValueError(
                f"Invalid compute_backend '{cfg.compute_backend}', "
                f"must be one of {valid_compute_backends}"
            )

        valid_env_types = {"conda", "venv"}
        if cfg.remote_env_type not in valid_env_types:
            raise ValueError(
                f"Invalid remote_env_type '{cfg.remote_env_type}', "
                f"must be one of {valid_env_types}"
            )
        if cfg.local_env_type not in valid_env_types:
            raise ValueError(
                f"Invalid local_env_type '{cfg.local_env_type}', "
                f"must be one of {valid_env_types}"
            )

        valid_languages = {"zh", "en"}
        if cfg.language not in valid_languages:
            raise ValueError(
                f"Invalid language '{cfg.language}', "
                f"must be one of {valid_languages}"
            )

        if isinstance(cfg.research_focus, bool) or not isinstance(cfg.research_focus, int) or not 1 <= cfg.research_focus <= 5:
            raise ValueError(
                f"Invalid research_focus '{cfg.research_focus}', "
                f"must be an integer between 1 and 5"
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
        workspaces_dir_base: Path | None = None
        orchestra_skills_dir_base: Path | None = None
        for path in paths:
            config_path = Path(path).expanduser().resolve()
            with open(config_path, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            if "workspaces_dir" in data:
                workspaces_dir_base = config_path.parent
            if "orchestra_skills_dir" in data:
                orchestra_skills_dir_base = config_path.parent
            for key, val in data.items():
                if isinstance(val, dict) and isinstance(merged.get(key), dict):
                    merged[key].update(val)
                else:
                    merged[key] = val
        if workspaces_dir_base is not None and "workspaces_dir" in merged:
            merged["workspaces_dir"] = str(
                cls._resolve_local_path(str(merged["workspaces_dir"]), workspaces_dir_base)
            )
        if orchestra_skills_dir_base is not None and "orchestra_skills_dir" in merged:
            merged["orchestra_skills_dir"] = str(
                cls._resolve_local_path(
                    str(merged["orchestra_skills_dir"]),
                    orchestra_skills_dir_base,
                )
            )
        base_dir = Path(paths[-1]).expanduser().resolve().parent if paths else Path.cwd()
        cfg = cls._from_data(merged, base_dir=base_dir)
        for agent_name in ["ideation", "planning", "experiment", "writing"]:
            if agent_name in merged:
                setattr(cfg, agent_name, AgentConfig(**merged[agent_name]))
        for key in [
            "max_parallel_tasks", "experiment_timeout", "review_enabled",
            "ssh_server", "remote_base", "gpus_per_task", "max_gpus",
            "gpu_poll_enabled", "gpu_free_threshold_mb",
            "gpu_poll_interval_sec", "gpu_poll_max_attempts",
            "gpu_aggressive_mode", "gpu_aggressive_threshold_pct",
            "pilot_samples", "pilot_timeout",
            "research_focus",
            "debate_rounds", "writing_revision_rounds",
            "lark_enabled", "evolution_enabled",
            "idea_exp_cycles", "idea_validation_rounds",
            "max_iterations", "max_iterations_cap",
            "compute_backend",
            "codex_enabled", "codex_model", "codex_idea_rounds",
            "writing_mode", "codex_writing_model",
            "experiment_mode", "server_codex_path", "server_claude_path",
            "remote_env_type", "remote_conda_path", "remote_conda_env_name",
            "iteration_dirs",
            "local_env_type", "local_conda_path", "local_conda_env_name",
            "language",
            "self_heal_enabled", "self_heal_interval_sec", "self_heal_max_attempts",
            "supervisor_enabled",
            "orchestra_skills_enabled", "orchestra_skills_dir", "orchestra_skills_max",
        ]:
            if key in merged:
                setattr(cfg, key, merged[key])
        for key in ["pilot_seeds", "full_seeds"]:
            if key in merged:
                setattr(cfg, key, merged[key])
        for key in ["model_tiers", "agent_tier_map"]:
            if key in merged:
                getattr(cfg, key).update(merged[key])

        valid_compute_backends = {"local", "ssh"}
        if cfg.compute_backend not in valid_compute_backends:
            raise ValueError(
                f"Invalid compute_backend '{cfg.compute_backend}', "
                f"must be one of {valid_compute_backends}"
            )

        valid_env_types = {"conda", "venv"}
        if cfg.remote_env_type not in valid_env_types:
            raise ValueError(
                f"Invalid remote_env_type '{cfg.remote_env_type}', "
                f"must be one of {valid_env_types}"
            )
        if cfg.local_env_type not in valid_env_types:
            raise ValueError(
                f"Invalid local_env_type '{cfg.local_env_type}', "
                f"must be one of {valid_env_types}"
            )

        valid_languages = {"zh", "en"}
        if cfg.language not in valid_languages:
            raise ValueError(
                f"Invalid language '{cfg.language}', "
                f"must be one of {valid_languages}"
            )

        if isinstance(cfg.research_focus, bool) or not isinstance(cfg.research_focus, int) or not 1 <= cfg.research_focus <= 5:
            raise ValueError(
                f"Invalid research_focus '{cfg.research_focus}', "
                f"must be an integer between 1 and 5"
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

    def get_remote_env_cmd(self, project_name: str) -> str:
        """Return the environment activation command for remote execution."""
        if self.remote_env_type == "venv":
            return f"source {self.remote_base}/projects/{project_name}/.venv/bin/activate &&"
        conda = self.remote_conda_path or f"{self.remote_base}/miniconda3/bin/conda"
        env_name = self.remote_conda_env_name or f"sibyl_{project_name}"
        return f"{conda} run -n {env_name}"

    def get_local_env_cmd(self, project_name: str) -> str:
        """Return the environment activation command for local execution."""
        if self.local_env_type == "venv":
            return f"source .venv/bin/activate &&"
        conda = self.local_conda_path or "conda"
        env_name = self.local_conda_env_name or f"sibyl_{project_name}"
        return f"{conda} run -n {env_name}"

    def to_dict(self) -> dict:
        """Serialize config for persisting into a project workspace."""
        data = asdict(self)
        data["workspaces_dir"] = str(self.workspaces_dir)
        return data

    def to_yaml(self) -> str:
        """Serialize config as YAML for workspace/config.yaml snapshots."""
        return yaml.safe_dump(self.to_dict(), allow_unicode=True, sort_keys=False)

    def to_commented_yaml(self) -> str:
        """Serialize config as human-friendly YAML with section headers and comments."""
        d = self.to_dict()

        def _val(key: str) -> str:
            v = d[key]
            if isinstance(v, bool):
                return "true" if v else "false"
            if isinstance(v, str):
                return f'"{v}"' if not v else str(v)
            if isinstance(v, list):
                return "[" + ", ".join(str(x) for x in v) + "]"
            return str(v)

        def _dict_block(key: str, indent: int = 2) -> str:
            lines = []
            prefix = " " * indent
            for k, v in d[key].items():
                lines.append(f"{prefix}{k}: {v}")
            return "\n".join(lines)

        return f"""\
# Sibyl Research System — Project Configuration
# Edit this file to customize project behavior.
# Config priority: --config flag > project config.yaml > system config.yaml > defaults

# ── Language ─────────────────────────────────────────────────────────
# Agent output language ("zh" | "en"). Papers are always English.
language: {_val('language')}

# ── Compute Backend ──────────────────────────────────────────────────
# "local" = run experiments on local GPUs directly (default)
# "ssh"   = run experiments on remote GPU server via SSH
compute_backend: {_val('compute_backend')}

# ── Local GPU (compute_backend: local) ───────────────────────────────
local_env_type: {_val('local_env_type')}                     # "conda" | "venv"
local_conda_path: {_val('local_conda_path')}                    # empty = system conda
local_conda_env_name: {_val('local_conda_env_name')}               # empty = auto: sibyl_{{project}}

# ── Remote GPU (compute_backend: ssh) ────────────────────────────────
ssh_server: {_val('ssh_server')}                       # SSH MCP connection name
remote_base: {_val('remote_base')}    # remote GPU server path
remote_env_type: {_val('remote_env_type')}                    # "conda" | "venv"
remote_conda_path: {_val('remote_conda_path')}                   # empty = auto
remote_conda_env_name: {_val('remote_conda_env_name')}              # empty = auto: sibyl_{{project}}

# ── GPU Scheduling ──────────────────────────────────────────────────
max_gpus: {_val('max_gpus')}
gpus_per_task: {_val('gpus_per_task')}

# GPU polling (shared servers)
gpu_poll_enabled: {_val('gpu_poll_enabled')}
gpu_free_threshold_mb: {_val('gpu_free_threshold_mb')}             # VRAM threshold (MB)
gpu_poll_interval_sec: {_val('gpu_poll_interval_sec')}              # poll interval (seconds)
gpu_poll_max_attempts: {_val('gpu_poll_max_attempts')}                # 0 = infinite

# Aggressive mode: claim GPUs with low utilization
gpu_aggressive_mode: {_val('gpu_aggressive_mode')}
gpu_aggressive_threshold_pct: {_val('gpu_aggressive_threshold_pct')}        # VRAM usage % threshold

# ── Research Focus ──────────────────────────────────────────────────
# 1=explore (pivot early), 2=open, 3=balanced (default), 4=focused, 5=deep_focus (persist)
research_focus: {_val('research_focus')}

# ── Experiment Pipeline ─────────────────────────────────────────────
idea_exp_cycles: {_val('idea_exp_cycles')}                     # idea→experiment cycles
idea_validation_rounds: {_val('idea_validation_rounds')}            # pilot decision debate rounds
max_iterations: {_val('max_iterations')}                     # soft iteration limit
max_iterations_cap: {_val('max_iterations_cap')}                 # hard cap
experiment_timeout: {_val('experiment_timeout')}                 # per-experiment timeout (seconds)
iteration_dirs: {_val('iteration_dirs')}                 # default: true (current -> iter_001/ subdirectories)

# ── Pilot Experiments ───────────────────────────────────────────────
# Use 100+ samples for reliable signal (n=16 causes signal reversal)
pilot_samples: {_val('pilot_samples')}
pilot_timeout: {_val('pilot_timeout')}                      # seconds
pilot_seeds: {_val('pilot_seeds')}

# ── Full Experiments ────────────────────────────────────────────────
full_seeds: {_val('full_seeds')}

# ── Experiment Execution ────────────────────────────────────────────
experiment_mode: {_val('experiment_mode')}              # "ssh_mcp" | "server_codex" | "server_claude"
server_codex_path: {_val('server_codex_path')}                # Codex CLI path on server
server_claude_path: {_val('server_claude_path')}              # Claude CLI path on server

# ── Multi-Agent Debate ──────────────────────────────────────────────
debate_rounds: {_val('debate_rounds')}
writing_revision_rounds: {_val('writing_revision_rounds')}
max_parallel_tasks: {_val('max_parallel_tasks')}

# ── Writing ─────────────────────────────────────────────────────────
# "sequential" (best coherence) | "parallel" (faster) | "codex" (gpt-5.4)
writing_mode: {_val('writing_mode')}
review_enabled: {_val('review_enabled')}

# ── Codex Integration ───────────────────────────────────────────────
codex_enabled: {_val('codex_enabled')}
codex_model: {_val('codex_model')}                         # empty = Codex default
codex_writing_model: {_val('codex_writing_model')}                 # empty = Codex default
codex_idea_rounds: {_val('codex_idea_rounds')}                    # Codex-guided idea refinement rounds (0 = skip)

# ── Integrations ────────────────────────────────────────────────────
lark_enabled: {_val('lark_enabled')}                     # Feishu/Lark doc sync
evolution_enabled: {_val('evolution_enabled')}                # auto prompt evolution
self_heal_enabled: {_val('self_heal_enabled')}                # auto error fix
self_heal_interval_sec: {_val('self_heal_interval_sec')}             # scan interval (seconds)
self_heal_max_attempts: {_val('self_heal_max_attempts')}               # circuit breaker threshold

# ── Orchestra External Skills ──────────────────────────────────────
# Inject external skill index into agent prompts for on-demand invocation
orchestra_skills_enabled: {_val('orchestra_skills_enabled')}
orchestra_skills_dir: {_val('orchestra_skills_dir')}
orchestra_skills_max: {_val('orchestra_skills_max')}                 # max skills per agent prompt

# ── Model Routing ───────────────────────────────────────────────────
model_tiers:
{_dict_block('model_tiers')}

agent_tier_map:
{_dict_block('agent_tier_map')}

# ── Workspace root (parent directory that contains all projects) ────
workspaces_dir: {_val('workspaces_dir')}
"""
