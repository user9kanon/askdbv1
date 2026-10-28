"""Cross-reference and source-DB validation for a database config (SPEC §4.2, §11.4).

All rules fail closed. Every problem is collected and raised together as one
`ConfigError`; the app refuses to start on any of them.
"""

from __future__ import annotations

import os
import re
import sqlite3
from collections import Counter
from contextlib import closing
from pathlib import Path

from askdb.config.loader import ConfigError, load_config
from askdb.config.models import DatabaseConfig, Metric

CONFIG_ENV = "ASKDB_DATABASE_CONFIG"
ALL_GROUPS = "All"
FILTERS_PLACEHOLDER = "{{filters}}"
_DATE_TYPES = {"DATE", "DATETIME"}


def open_source_readonly(path: str | os.PathLike[str]) -> sqlite3.Connection:
    """Open the source DB read-only. Only config validation and the scope builder may."""
    uri = Path(path).resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.execute("PRAGMA query_only = ON")
    return conn


def validate_config(cfg: DatabaseConfig) -> list[str]:
    """Check `cfg` against itself and its source DB. Returns warnings; raises on errors."""
    errors: list[str] = []
    warnings: list[str] = []
    _check_tables(cfg, errors)
    if cfg.access is None:
        warnings.append("no `access` section: there is no row scoping, every user sees all rows")
        errors += [
            f"tables.{t.name}.{c.name}: sensitive category {c.sensitive!r} is not declared"
            for t in cfg.tables
            for c in t.columns
            if c.sensitive
        ]
    else:
        _check_access(cfg, errors)
    _check_metric_shapes(cfg, errors)
    if errors:
        raise ConfigError(errors)

    if not Path(cfg.path).is_file():
        raise ConfigError(f"path: source database {cfg.path} does not exist")
    with closing(open_source_readonly(cfg.path)) as conn:
        _check_against_db(cfg, conn, errors)
        if not errors:
            _check_metric_sql(cfg, conn, errors)
    if errors:
        raise ConfigError(errors)
    return warnings


def load_validated_config(path: str | os.PathLike[str] | None = None) -> DatabaseConfig:
    """Load and fully validate the config named by `path` or `$ASKDB_DATABASE_CONFIG`."""
    if path is None:
        path = os.environ.get(CONFIG_ENV)
        if not path:
            raise ConfigError(f"{CONFIG_ENV} is not set")
    cfg = load_config(path)
    validate_config(cfg)
    return cfg


def duplicates(names: list[str]) -> list[str]:
    return [n for n, k in Counter(names).items() if k > 1]


def _check_tables(cfg: DatabaseConfig, errors: list[str]) -> None:
    errors += [f"tables: duplicate table {n!r}" for n in duplicates([t.name for t in cfg.tables])]
    for t in cfg.tables:
        where = f"tables.{t.name}"
        errors += [
            f"{where}: duplicate column {n!r}" for n in duplicates([c.name for c in t.columns])
        ]
        if sum(c.primary_key for c in t.columns) > 1:
            errors.append(f"{where}: more than one primary_key column")
        if sum(c.display_name for c in t.columns) > 1:
            errors.append(f"{where}: more than one display_name column")
        if any(c.display_name for c in t.columns) and t.primary_key is None:
            errors.append(f"{where}: display_name requires the table to have a primary_key")
        for c in t.columns:
            if c.references is None:
                continue
            ref_t, ref_c = c.references.split(".")
            target = cfg.table(ref_t)
            if target is None or target.column(ref_c) is None:
                errors.append(f"{where}.{c.name}: references unknown column {c.references}")


def _check_access(cfg: DatabaseConfig, errors: list[str]) -> None:
    assert cfg.access is not None
    rs = cfg.access.row_scope
    cats = cfg.access.sensitive_categories

    for t in cfg.tables:
        for c in t.columns:
            if c.sensitive and c.sensitive not in cats:
                errors.append(
                    f"tables.{t.name}.{c.name}: sensitive category {c.sensitive!r} is not declared"
                )

    root = cfg.table(rs.table)
    if root is None:
        errors.append(f"access.row_scope.table: unknown table {rs.table!r}")
    else:
        if root.column(rs.column) is None:
            errors.append(f"access.row_scope.column: {rs.table}.{rs.column} is not a listed column")
        if root.primary_key is None:
            errors.append(f"access.row_scope.table: {rs.table} needs a primary_key column")
    if ALL_GROUPS in rs.groups:
        errors.append(
            f"access.row_scope.groups: {ALL_GROUPS!r} is reserved for the all-groups grant"
        )

    # Every table appears in exactly one of row_scope.table, scoped_tables, reference_tables.
    placed = [rs.table, *(s.table for s in rs.scoped_tables), *rs.reference_tables]
    for name in duplicates(placed):
        errors.append(
            f"access: table {name!r} appears more than once in row_scope/scoped/reference"
        )
    for name in placed:
        if cfg.table(name) is None:
            errors.append(f"access: unknown table {name!r}")
    for t in cfg.tables:
        if t.name not in placed:
            errors.append(
                f"access: table {t.name!r} is not in row_scope.table, scoped_tables "
                "or reference_tables"
            )

    # Each `via` must reference the primary key of the root or another scoped table.
    scoped = {s.table for s in rs.scoped_tables}
    parent: dict[str, str] = {}
    for s in rs.scoped_tables:
        where = f"access.row_scope.scoped_tables.{s.table}"
        table = cfg.table(s.table)
        if table is None:
            continue
        col = table.column(s.via)
        if col is None:
            errors.append(f"{where}: via column {s.via!r} is not a listed column")
            continue
        if col.references is None:
            errors.append(f"{where}: via column {s.via!r} declares no `references`")
            continue
        ref_t, ref_c = col.references.split(".")
        target = cfg.table(ref_t)
        if ref_t != rs.table and ref_t not in scoped:
            errors.append(
                f"{where}: via {s.via} references {ref_t}, which is neither "
                "row_scope.table nor a scoped table"
            )
        elif target is None or target.primary_key is None or target.primary_key.name != ref_c:
            errors.append(f"{where}: via {s.via} must reference the primary key of {ref_t}")
        else:
            parent[s.table] = ref_t

    # Chains must end at the root, without cycles.
    for start in parent:
        seen = [start]
        node = start
        while node in parent:
            node = parent[node]
            if node in seen:
                if start == min(seen[seen.index(node) :]):
                    cycle = " -> ".join([*seen[seen.index(node) :], node])
                    errors.append(f"access.row_scope.scoped_tables: cycle {cycle}")
                break
            seen.append(node)


def _check_metric_shapes(cfg: DatabaseConfig, errors: list[str]) -> None:
    errors += [f"metrics: duplicate name {n!r}" for n in duplicates([m.name for m in cfg.metrics])]
    for m in cfg.metrics:
        where = f"metrics.{m.name}"
        if m.kind == "period":
            for p in ("start", "end"):
                if not re.search(rf":{p}\b", m.sql):
                    errors.append(f"{where}: period metric sql must use :{p}")
            if m.time_column is None:
                errors.append(f"{where}: period metric needs time_column")
            else:
                t_name, c_name = m.time_column.split(".")
                t = cfg.table(t_name)
                col = t.column(c_name) if t else None
                if col is None:
                    errors.append(f"{where}: time_column {m.time_column} is not a listed column")
                elif col.type not in _DATE_TYPES:
                    errors.append(f"{where}: time_column {m.time_column} is not DATE or DATETIME")
            if m.breakdown_sql is not None:
                errors.append(f"{where}: breakdown_sql is for snapshot metrics only")
        else:
            for key in ("time_column", "trend"):
                if getattr(m, key) is not None:
                    errors.append(f"{where}: {key} is for period metrics only")
            for sql in (m.sql, m.breakdown_sql or ""):
                if re.search(r":(start|end)\b", sql):
                    errors.append(f"{where}: snapshot metric sql must not use :start/:end")
        if m.filters and FILTERS_PLACEHOLDER not in m.sql:
            errors.append(f"{where}: has filters but sql has no {FILTERS_PLACEHOLDER}")


def _check_against_db(cfg: DatabaseConfig, conn: sqlite3.Connection, errors: list[str]) -> None:
    for t in cfg.tables:
        rows = conn.execute("SELECT name FROM pragma_table_info(?)", (t.name,)).fetchall()
        if not rows:
            errors.append(f"tables.{t.name}: table does not exist in the source database")
            continue
        existing = {r[0] for r in rows}
        for c in t.columns:
            if c.name not in existing:
                errors.append(
                    f"tables.{t.name}.{c.name}: column does not exist in the source database"
                )


def _run_metric_sql(metric: Metric, sql: str, conn: sqlite3.Connection) -> list[str]:
    """Run with every filter applied (bound to NULL) and a dummy period; return column names."""
    clause = "".join(f" AND {expr} = :f_{name}" for name, expr in metric.filters.items())
    params: dict[str, object] = {f"f_{name}": None for name in metric.filters}
    if metric.kind == "period":
        params |= {"start": "2000-01-01", "end": "2000-01-02"}
    cur = conn.execute(sql.replace(FILTERS_PLACEHOLDER, clause), params)
    cur.fetchmany(1)
    return [d[0] for d in cur.description or []]


def _check_metric_sql(cfg: DatabaseConfig, conn: sqlite3.Connection, errors: list[str]) -> None:
    for m in cfg.metrics:
        for key, sql, want in (
            ("sql", m.sql, {"value"}),
            ("breakdown_sql", m.breakdown_sql, {"label", "value"}),
        ):
            if sql is None:
                continue
            where = f"metrics.{m.name}.{key}"
            if not re.match(r"\s*(SELECT|WITH)\b", sql, re.IGNORECASE):
                errors.append(f"{where}: must be a single SELECT")
                continue
            try:
                cols = _run_metric_sql(m, sql, conn)
            except (sqlite3.Error, sqlite3.Warning) as e:
                errors.append(f"{where}: fails on the source database: {e}")
                continue
            if missing := want - set(cols):
                errors.append(
                    f"{where}: result has no column(s) named {', '.join(sorted(missing))}"
                )
