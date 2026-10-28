"""Pydantic models for the database config format (SPEC §4.2).

Every model forbids unknown keys: a typo in `access` must never silently disable
scoping. Cross-references between sections are checked in `validate.py`.
"""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator

Slug = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*$")]
Identifier = Annotated[str, Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")]
ColumnRef = Annotated[str, Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*$")]
NonEmpty = Annotated[str, Field(min_length=1)]

ColumnType = Literal["INTEGER", "REAL", "TEXT", "DATE", "DATETIME"]
NAMED_UNITS = {"count", "ratio", "hours", "number"}


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Calendar(Strict):
    fiscal_year_start_month: int = Field(default=1, ge=1, le=12)


class DataCoverage(Strict):
    mode: Literal["live", "static_snapshot"] = "live"
    expected_cadence: Literal["hourly", "daily", "weekly"] | None = None
    start: dt.date | None = None
    end: dt.date | None = None


class Column(Strict):
    name: Identifier
    type: ColumnType
    description: str | None = None
    primary_key: StrictBool = False
    references: ColumnRef | None = None
    sensitive: Slug | None = None
    indexable: StrictBool | None = None
    display_name: StrictBool = False


class Table(Strict):
    name: Identifier
    description: NonEmpty
    columns: list[Column] = Field(min_length=1)

    def column(self, name: str) -> Column | None:
        return next((c for c in self.columns if c.name == name), None)

    @property
    def primary_key(self) -> Column | None:
        return next((c for c in self.columns if c.primary_key), None)


class ScopedTable(Strict):
    table: Identifier
    via: Identifier


class RowScope(Strict):
    table: Identifier
    column: Identifier
    group_label: NonEmpty
    groups: dict[NonEmpty, list[NonEmpty]] = Field(min_length=1)
    scoped_tables: list[ScopedTable] = Field(default_factory=list)
    reference_tables: list[Identifier] = Field(default_factory=list)


class SensitiveCategory(Strict):
    label: NonEmpty
    description: str | None = None


class Access(Strict):
    row_scope: RowScope
    sensitive_categories: dict[Slug, SensitiveCategory] = Field(default_factory=dict)


class Trend(Strict):
    grain: Literal["month", "quarter", "year"]
    periods: int = Field(ge=1)


class Metric(Strict):
    name: Slug
    label: NonEmpty
    synonyms: list[NonEmpty] = Field(default_factory=list)
    kind: Literal["period", "snapshot"]
    unit: str
    time_column: ColumnRef | None = None
    sql: NonEmpty
    filters: dict[Slug, NonEmpty] = Field(default_factory=dict)
    trend: Trend | None = None
    breakdown_sql: NonEmpty | None = None

    @field_validator("unit")
    @classmethod
    def _unit(cls, v: str) -> str:
        if v in NAMED_UNITS or (len(v) == 3 and v.isalpha()):
            return v
        raise ValueError(f"must be a currency code or one of {sorted(NAMED_UNITS)}")


class DatabaseConfig(Strict):
    name: Slug
    display_name: NonEmpty
    path: NonEmpty
    calendar: Calendar = Field(default_factory=Calendar)
    data_coverage: DataCoverage = Field(default_factory=DataCoverage)
    description: NonEmpty
    tables: list[Table] = Field(min_length=1)
    access: Access | None = None
    metrics: list[Metric] = Field(default_factory=list)

    def table(self, name: str) -> Table | None:
        return next((t for t in self.tables if t.name == name), None)
