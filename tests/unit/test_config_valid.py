"""Valid configs load and validate (SPEC 4.2, 11.4)."""

from pathlib import Path

import pytest

from askdb.cli import main
from askdb.config import (
    ConfigError,
    load_config,
    load_validated_config,
    parse_config,
    validate_config,
)
from askdb.config.loader import read_yaml
from tests.conftest import CLOUDMETRICS_CONFIG, CLOUDMETRICS_DB, SYNTHETIC_CONFIG


def test_cloudmetrics_config_is_valid():
    cfg = load_config(CLOUDMETRICS_CONFIG)
    assert validate_config(cfg) == []
    assert cfg.name == "cloudmetrics"
    assert Path(cfg.path) == CLOUDMETRICS_DB.resolve()
    assert cfg.data_coverage.mode == "static_snapshot"
    assert {t.name for t in cfg.tables} == {
        "customers",
        "plans",
        "subscriptions",
        "invoices",
        "support_tickets",
    }
    assert len(cfg.metrics) == 8
    # YAML anchors resolve to the same filter map.
    by_name = {m.name: m for m in cfg.metrics}
    assert by_name["arpu"].filters == by_name["mrr"].filters


def test_synthetic_multi_hop_config_is_valid():
    cfg = load_config(SYNTHETIC_CONFIG)
    assert validate_config(cfg) == []
    assert cfg.metrics == []
    assert cfg.access.row_scope.column == "territory"
    assert [s.table for s in cfg.access.row_scope.scoped_tables] == ["orders", "order_items"]


def test_missing_access_is_a_warning_not_an_error(synthetic_raw):
    del synthetic_raw["access"]
    for t in synthetic_raw["tables"]:
        for c in t["columns"]:
            c.pop("sensitive", None)
    warnings = validate_config(parse_config(synthetic_raw))
    assert any("no row scoping" in w for w in warnings)


def test_load_validated_config_reads_env(monkeypatch):
    monkeypatch.setenv("ASKDB_DATABASE_CONFIG", str(CLOUDMETRICS_CONFIG))
    assert load_validated_config().name == "cloudmetrics"


def test_cli_validate_config_ok(monkeypatch, capsys):
    monkeypatch.setenv("ASKDB_DATABASE_CONFIG", str(CLOUDMETRICS_CONFIG))
    assert main(["validate-config"]) == 0
    assert "OK" in capsys.readouterr().out


def test_cli_validate_config_reports_errors(tmp_path, capsys):
    bad = tmp_path / "bad.yaml"
    bad.write_text(CLOUDMETRICS_CONFIG.read_text(encoding="utf-8") + "\nbogus: 1\n", "utf-8")
    assert main(["validate-config", "--config", str(bad)]) == 1
    assert "bogus: unknown key" in capsys.readouterr().err


def test_cli_without_config_is_usage_error(monkeypatch):
    monkeypatch.delenv("ASKDB_DATABASE_CONFIG", raising=False)
    assert main(["validate-config"]) == 2


def test_config_is_loaded_with_safe_loader(tmp_path):
    evil = tmp_path / "evil.yaml"
    evil.write_text("name: !!python/object/apply:os.getcwd []\n", "utf-8")
    with pytest.raises(ConfigError, match="invalid YAML"):
        read_yaml(evil)
