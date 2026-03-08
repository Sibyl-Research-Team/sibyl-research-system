from dataclasses import dataclass, field
from pathlib import Path
import yaml


@dataclass
class AgentConfig:
    model: str = "claude-opus-4-6"
    max_tokens: int = 64000
    temperature: float = 0.7


@dataclass
class Config:
    workspaces_dir: Path = Path("workspaces")
    ideation: AgentConfig = field(default_factory=lambda: AgentConfig(temperature=0.9))
    planning: AgentConfig = field(default_factory=AgentConfig)
    experiment: AgentConfig = field(default_factory=lambda: AgentConfig(temperature=0.3))
    writing: AgentConfig = field(default_factory=lambda: AgentConfig(temperature=0.5))
    max_parallel_tasks: int = 4
    idea_exp_cycles: int = 3
    experiment_timeout: int = 300
    review_enabled: bool = True

    # GPU scheduling
    gpu_ids: list[int] = field(default_factory=lambda: [0, 1, 2, 3])
    ssh_server: str = "cs8000d"
    remote_base: str = "/home/ccwang/sibyl_system"

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
    codex_enabled: bool = True
    codex_model: str = ""  # Codex model (empty = use default; ChatGPT accounts don't support custom models)

    # Writing mode
    writing_mode: str = "sequential"  # "sequential" | "parallel" | "codex"
    codex_writing_model: str = ""  # Codex writing model (empty = use default)

    # Experiment execution
    experiment_mode: str = "ssh_mcp"  # "ssh_mcp" | "server_codex" | "server_claude"
    server_codex_path: str = "codex"  # Codex CLI path on server
    server_claude_path: str = "claude"  # Claude CLI path on server

    # Lark sync
    lark_enabled: bool = True

    # Auto evolution
    evolution_enabled: bool = True

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
            "ssh_server", "remote_base",
            "pilot_samples", "pilot_timeout",
            "debate_rounds", "writing_revision_rounds",
            "lark_enabled", "evolution_enabled",
            "idea_exp_cycles",
            "codex_enabled", "codex_model", "writing_mode", "codex_writing_model",
            "experiment_mode", "server_codex_path", "server_claude_path",
        ]:
            if key in data:
                setattr(cfg, key, data[key])
        # List fields
        for key in ["gpu_ids", "pilot_seeds", "full_seeds"]:
            if key in data:
                setattr(cfg, key, data[key])
        # Dict fields (model routing)
        for key in ["model_tiers", "agent_tier_map"]:
            if key in data:
                getattr(cfg, key).update(data[key])

        # Validate enum-like fields
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
