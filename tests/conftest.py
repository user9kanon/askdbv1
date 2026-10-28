"""Shared fixtures: the CloudMetrics dev dataset and the synthetic multi-hop database."""

from __future__ import annotations

import copy
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from askdb.config.loader import read_yaml

ROOT = Path(__file__).resolve().parent.parent
CLOUDMETRICS_CONFIG = ROOT / "test" / "cloudmetrics.yaml"
CLOUDMETRICS_EVAL = ROOT / "test" / "cloudmetrics_eval.yaml"
CLOUDMETRICS_DB = ROOT / "test" / "cloudmetrics.db"
SYNTHETIC_DIR = Path(__file__).resolve().parent / "fixtures" / "synthetic"
SYNTHETIC_CONFIG = SYNTHETIC_DIR / "synthetic.yaml"


@pytest.fixture(scope="session")
def synthetic_db(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("synthetic") / "synthetic.db"
    with sqlite3.connect(path) as conn:
        conn.executescript((SYNTHETIC_DIR / "schema.sql").read_text(encoding="utf-8"))
    conn.close()
    return path


@pytest.fixture(autouse=True)
def _source_db_env(monkeypatch: pytest.MonkeyPatch, synthetic_db: Path) -> None:
    """Point the configs' `${VAR}` paths at the fixture databases."""
    monkeypatch.setenv("CLOUDMETRICS_DB_PATH", str(CLOUDMETRICS_DB))
    monkeypatch.setenv("SYNTHETIC_DB_PATH", str(synthetic_db))


@pytest.fixture
def cloudmetrics_raw() -> dict[str, Any]:
    """The CloudMetrics config as a plain dict, safe to mutate per test."""
    return copy.deepcopy(_raw(CLOUDMETRICS_CONFIG))


@pytest.fixture
def synthetic_raw() -> dict[str, Any]:
    return copy.deepcopy(_raw(SYNTHETIC_CONFIG))


_cache: dict[Path, Any] = {}


def _raw(path: Path) -> Any:
    if path not in _cache:
        _cache[path] = read_yaml(path)
    return _cache[path]
