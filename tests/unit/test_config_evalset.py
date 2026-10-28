"""Validation dataset format (SPEC 4.3)."""

from __future__ import annotations

import copy

import pytest

from askdb.config import ConfigError, load_config, parse_config
from askdb.config.loader import parse_model, read_yaml
from askdb.evalset import EvalSet, load_evalset, validate_evalset
from tests.conftest import CLOUDMETRICS_CONFIG, CLOUDMETRICS_EVAL


@pytest.fixture
def eval_raw():
    return copy.deepcopy(read_yaml(CLOUDMETRICS_EVAL))


def parse(raw) -> EvalSet:
    return parse_model(EvalSet, raw)


def test_cloudmetrics_evalset_is_valid():
    ev = load_evalset(CLOUDMETRICS_EVAL)
    validate_evalset(ev, load_config(CLOUDMETRICS_CONFIG))
    assert len(ev.cases) == 29
    assert sum(c.is_follow_up for c in ev.cases) == 1
    assert {c.expected_outcome for c in ev.cases} == {None, "clarification", "declined"}
    today = next(c for c in ev.cases if c.id == "recent_churn_relative").today
    assert today.isoformat() == "2026-10-21"


def test_case_needs_exactly_one_expectation(eval_raw):
    eval_raw["cases"][0]["expected_outcome"] = "declined"
    with pytest.raises(ConfigError, match="exactly one of expected_sql and expected_outcome"):
        parse(eval_raw)


def test_unknown_case_key(eval_raw):
    eval_raw["cases"][0]["expected"] = "x"
    with pytest.raises(ConfigError, match="unknown key"):
        parse(eval_raw)


def test_duplicate_case_ids(eval_raw):
    eval_raw["cases"][1]["id"] = eval_raw["cases"][0]["id"]
    with pytest.raises(ConfigError, match="duplicate case id"):
        parse(eval_raw)


def test_database_must_match_config(eval_raw, cloudmetrics_raw):
    eval_raw["database"] = "other"
    with pytest.raises(ConfigError, match="does not match config name"):
        validate_evalset(parse(eval_raw), parse_config(cloudmetrics_raw))


def test_expected_sql_must_run(eval_raw, cloudmetrics_raw):
    eval_raw["cases"][0]["expected_sql"] = "SELECT nope FROM subscriptions"
    with pytest.raises(ConfigError, match="total_mrr.expected_sql: fails"):
        validate_evalset(parse(eval_raw), parse_config(cloudmetrics_raw))
