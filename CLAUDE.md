# CLAUDE.md

AskDB is a local web app that lets executives and managers ask KPI questions in plain English and get a headline number, an interpretation line and a chart.
It is strictly read-only and data-agnostic: each user queries a per-scope SQLite copy holding only the rows and columns they may see.

## Source of truth
- `docs/SPEC.md` is authoritative. Read the relevant section before you implement, and cite it (e.g. §6.2). If code and spec disagree, raise it; don't silently diverge.
- `docs/PLAN.md` tracks progress. Update it when you start or finish a piece of work.

## Stack
Python 3.12 (uv), FastAPI, Jinja2 + HTMX, Chart.js, stdlib `sqlite3`, PyYAML (safe loader) + Pydantic, sqlglot (SQLite dialect), APScheduler, argon2, Anthropic API (Claude), pytest, ruff.

## Commands
```
uv sync                                   # install
uv run askdb create-admin                 # first admin
uv run askdb seed-demo                    # demo accounts with different scopes
uv run askdb serve                        # run (127.0.0.1 only)
uv run pytest                             # all tests
uv run pytest tests/unit/test_x.py::test_y   # single test
uv run pytest tests/validation            # eval suite (needs ASKDB_VALIDATION_SET)
uv run ruff check . && uv run ruff format --check .   # lint
```
Development environment: `ASKDB_DATABASE_CONFIG=test/cloudmetrics.yaml`, `ASKDB_VALIDATION_SET=test/cloudmetrics_eval.yaml`, `CLOUDMETRICS_DB_PATH=test/cloudmetrics.db`.

## Layout
```
src/askdb/        app code (no domain-specific names, values or rules)
tests/unit/  tests/validation/  tests/ambiguity/  tests/redteam/
test/             CloudMetrics fixtures: cloudmetrics.db, .yaml config, _eval.yaml
docs/             SPEC.md, PLAN.md, one-pager.md
var/              app.db and scopes/*.db (generated, gitignored)
```

## Guardrails
- **Read-only SQL.** Open scope copies only, with a `mode=ro` URI and `PRAGMA query_only=ON`. A SQLite authorizer allows reads only, so ATTACH, PRAGMA, writes, DDL and transactions are denied. One statement per execution. No `'now'` or `CURRENT_*` in SQL.
- **Row cap and timeout.** Fetch at most 10,000 rows. A progress handler aborts queries after 5 s.
- **The query path never opens the source DB.** Only the scope builder and config validation do.
- **The LLM gets metadata only:** the config description, per-scope DDL and the metric catalog. Never rows, sample values or results.
- **Bind parameters only.** Never format filter values or periods into SQL strings.
- **Never commit secrets.** API keys and the session secret come from the environment only.
- **Never read `.env`.** Don't open, print or cat it. Ask the user if you need a value.
- **No CloudMetrics names in `src/`.** Everything domain-specific comes from the YAML config, which is validated strictly (unknown keys are an error).

## Conventions
- Every change comes with tests in the matching suite: unit for logic, redteam for anything touching scoping or execution, ambiguity for clarification and decline behaviour.
- Run `uv run pytest` and the lint command before calling work done, and report failures honestly.
- Failures in the validation, ambiguity or redteam suites block release (§11).
