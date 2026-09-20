"""Loading of config.yaml and selectors.yaml, with sane fallbacks to the
.example.yaml files so a fresh checkout can at least run `discover` before
the user copies/edits anything.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = REPO_ROOT / "config"


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _resolve(primary_name: str, example_name: str) -> Path:
    primary = CONFIG_DIR / primary_name
    if primary.exists():
        return primary
    example = CONFIG_DIR / example_name
    if example.exists():
        return example
    raise FileNotFoundError(
        f"Neither config/{primary_name} nor config/{example_name} exists."
    )


@dataclass
class ContentConfig:
    files: bool = True
    pages: bool = True
    announcements: bool = True
    grades: bool = True
    discussions: bool = True


@dataclass
class Config:
    base_url: str
    output_dir: Path
    profile_dir: Path
    log_dir: Path
    debug_dir: Path
    request_delay_seconds: float
    timeout_ms: int
    content: ContentConfig
    course_filter: list[str]
    log_level: str
    selectors: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def load(cls) -> "Config":
        config_path = _resolve("config.yaml", "config.example.yaml")
        selectors_path = _resolve("selectors.yaml", "selectors.example.yaml")

        raw = _load_yaml(config_path)
        selectors = _load_yaml(selectors_path)

        def resolve_path(key: str) -> Path:
            return (REPO_ROOT / raw[key]).resolve()

        return cls(
            base_url=raw["base_url"].rstrip("/"),
            output_dir=resolve_path("output_dir"),
            profile_dir=resolve_path("profile_dir"),
            log_dir=resolve_path("log_dir"),
            debug_dir=resolve_path("debug_dir"),
            request_delay_seconds=float(raw.get("request_delay_seconds", 1.5)),
            timeout_ms=int(raw.get("timeout_ms", 30000)),
            content=ContentConfig(**raw.get("content", {})),
            course_filter=list(raw.get("course_filter", []) or []),
            log_level=raw.get("log_level", "INFO"),
            selectors=selectors,
        )
