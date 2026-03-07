from dataclasses import dataclass, field
from pathlib import Path
import yaml


@dataclass
class AgentConfig:
    model: str = "claude-sonnet-4-20250514"
    max_tokens: int = 8192
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
    remote_base: str = "/home/ccwang/fars_pipeline"

    # Pilot experiments
    pilot_samples: int = 16
    pilot_timeout: int = 600  # 10 min
    pilot_seeds: list[int] = field(default_factory=lambda: [42])

    # Full experiments
    full_seeds: list[int] = field(default_factory=lambda: [42, 123, 456])

    # Multi-agent debate
    debate_rounds: int = 2
    writing_revision_rounds: int = 2

    # Lark sync
    lark_enabled: bool = False
    lark_app_token: str = ""

    # Auto evolution
    evolution_enabled: bool = True

    @classmethod
    def from_yaml(cls, path: str) -> "Config":
        with open(path) as f:
            data = yaml.safe_load(f)
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
            "lark_enabled", "lark_app_token", "evolution_enabled",
            "idea_exp_cycles",
        ]:
            if key in data:
                setattr(cfg, key, data[key])
        # List fields
        for key in ["gpu_ids", "pilot_seeds", "full_seeds"]:
            if key in data:
                setattr(cfg, key, data[key])
        return cfg
