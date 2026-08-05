from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"


class SeverityRule(BaseModel):
    enabled: bool = True
    silent: bool = True


DEFAULT_RULES = {
    "critical": SeverityRule(enabled=True, silent=False),
    "warning": SeverityRule(enabled=True, silent=True),
    "info": SeverityRule(enabled=True, silent=True),
}


class Project(BaseModel):
    name: str
    token: str
    thread_id: int
    severity_rules: dict[str, SeverityRule] = Field(default_factory=dict)

    def rule_for(self, severity: str, defaults: dict[str, SeverityRule]) -> SeverityRule:
        return self.severity_rules.get(severity, defaults.get(severity, SeverityRule()))


class Config(BaseModel):
    bot_token: str
    owner_chat_id: int
    dedup_cooldown_minutes: int = 15
    default_severity_rules: dict[str, SeverityRule] = Field(default_factory=lambda: dict(DEFAULT_RULES))
    projects: list[Project] = Field(default_factory=list)

    def project_by_token(self, token: str) -> Project | None:
        for project in self.projects:
            if project.token == token:
                return project
        return None

    def project_by_name(self, name: str) -> Project | None:
        for project in self.projects:
            if project.name == name:
                return project
        return None


def load_config(path: Path = CONFIG_PATH) -> Config:
    if not path.exists():
        raise FileNotFoundError(
            f"{path} не найден. Скопируйте config.example.yaml в config.yaml и заполните его."
        )
    raw = yaml.safe_load(path.read_text()) or {}
    return Config(**raw)


def save_config(config: Config, path: Path = CONFIG_PATH) -> None:
    data = config.model_dump(mode="json")
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False))
