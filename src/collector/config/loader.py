# What: read config.yaml, validate it, and fingerprint it.
# In: a path to a YAML file. Out: an AppConfig, or a ConfigError that names the problem.
"""Load and hash the configuration."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from collector.config.schema import AppConfig

DEFAULT_CONFIG_PATH = Path("config/config.yaml")


class ConfigError(Exception):
    """The configuration file is missing, unreadable or invalid."""


def load_config(path: Path | None = None) -> AppConfig:
    """Read and validate the YAML file; raise ConfigError with a clear message otherwise."""
    target = path or DEFAULT_CONFIG_PATH
    if not target.is_file():
        raise ConfigError(
            f"Config file not found: {target}. Copy config/config.example.yaml to {target}."
        )
    try:
        raw: Any = yaml.safe_load(target.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"Config file {target} is not valid YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"Config file {target} must contain a mapping at the top level.")
    try:
        return AppConfig.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(f"Config file {target} is invalid:\n{exc}") from exc


def config_hash(config: AppConfig) -> str:
    """A short fingerprint of the configuration, stamped on manifests and reports."""
    payload = json.dumps(config.model_dump(mode="json"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:12]
