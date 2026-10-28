"""Load a database config from YAML (safe loader) into strict models (SPEC §4.2)."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ValidationError

from askdb.config.models import DatabaseConfig

_ENV_VAR = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


class ConfigError(Exception):
    """A config, or validation dataset, failed validation. Carries every problem found."""

    def __init__(self, errors: list[str] | str):
        self.errors = [errors] if isinstance(errors, str) else list(errors)
        super().__init__("\n".join(f"- {e}" for e in self.errors))


def read_yaml(path: str | os.PathLike[str]) -> Any:
    try:
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f)
    except OSError as e:
        raise ConfigError(f"cannot read {path}: {e.strerror}") from e
    except yaml.YAMLError as e:
        raise ConfigError(f"invalid YAML in {path}: {e}") from e


def pydantic_errors(e: ValidationError) -> list[str]:
    out = []
    for err in e.errors():
        loc = ".".join(str(p) for p in err["loc"]) or "<root>"
        msg = "unknown key" if err["type"] == "extra_forbidden" else err["msg"]
        out.append(f"{loc}: {msg}")
    return out


def parse_model[M: BaseModel](model: type[M], data: Any) -> M:
    if not isinstance(data, dict):
        raise ConfigError("top level must be a mapping")
    try:
        return model.model_validate(data)
    except ValidationError as e:
        raise ConfigError(pydantic_errors(e)) from None


def expand_path(raw: str) -> Path:
    """Expand `${VAR}` from the environment; an unset variable is an error."""

    def sub(m: re.Match[str]) -> str:
        value = os.environ.get(m.group(1))
        if not value:
            raise ConfigError(f"path: environment variable {m.group(1)} is not set")
        return value

    return Path(_ENV_VAR.sub(sub, raw)).resolve()


def parse_config(data: Any) -> DatabaseConfig:
    """Validate a parsed YAML document and resolve `path` to an absolute file path."""
    cfg = parse_model(DatabaseConfig, data)
    return cfg.model_copy(update={"path": str(expand_path(cfg.path))})


def load_config(path: str | os.PathLike[str]) -> DatabaseConfig:
    return parse_config(read_yaml(path))
