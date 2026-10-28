"""Validation dataset (SPEC §4.3). Used only by the test suites, never at startup."""

from __future__ import annotations

import datetime as dt
import os
import sqlite3
from contextlib import closing
from typing import Literal, Self

from pydantic import Field, model_validator

from askdb.config.loader import ConfigError, parse_model, read_yaml
from askdb.config.models import DatabaseConfig, NonEmpty, Slug, Strict
from askdb.config.validate import duplicates, open_source_readonly

EVALSET_ENV = "ASKDB_VALIDATION_SET"


class Turn(Strict):
    question: NonEmpty
    sql: NonEmpty


class Case(Strict):
    id: Slug
    question: NonEmpty
    category: NonEmpty
    expected_sql: NonEmpty | None = None
    expected_outcome: Literal["clarification", "declined"] | None = None
    today: dt.date | None = None
    conversation: list[Turn] = Field(default_factory=list)
    notes: str | None = None

    @model_validator(mode="after")
    def _one_expectation(self) -> Self:
        if (self.expected_sql is None) == (self.expected_outcome is None):
            raise ValueError("exactly one of expected_sql and expected_outcome is required")
        return self

    @property
    def is_follow_up(self) -> bool:
        return bool(self.conversation)


class EvalSet(Strict):
    database: Slug
    cases: list[Case] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_ids(self) -> Self:
        if dupes := duplicates([c.id for c in self.cases]):
            raise ValueError(f"duplicate case id(s): {', '.join(dupes)}")
        return self


def load_evalset(path: str | os.PathLike[str]) -> EvalSet:
    return parse_model(EvalSet, read_yaml(path))


def validate_evalset(evalset: EvalSet, cfg: DatabaseConfig) -> None:
    """The set must name `cfg`, and every expected_sql must run on the source DB."""
    errors = []
    if evalset.database != cfg.name:
        errors.append(f"database: {evalset.database!r} does not match config name {cfg.name!r}")
    with closing(open_source_readonly(cfg.path)) as conn:
        for case in evalset.cases:
            if case.expected_sql is None:
                continue
            try:
                conn.execute(case.expected_sql).fetchmany(1)
            except (sqlite3.Error, sqlite3.Warning) as e:
                errors.append(f"cases.{case.id}.expected_sql: fails on the source database: {e}")
    if errors:
        raise ConfigError(errors)
