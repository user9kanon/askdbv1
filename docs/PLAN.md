# AskDB v1 — Plan

- [x] **Slice 1 — Project skeleton + strict config loading** (§4.2, §11.4)
  - Files: `pyproject.toml`, `src/askdb/__init__.py`, `src/askdb/cli.py`, `src/askdb/config/{models,loader,validate}.py`, `src/askdb/evalset.py`, `tests/conftest.py`, `tests/unit/test_config_*.py`, `tests/fixtures/synthetic/`, `docs/PLAN.md`
  - Verify: `uv run pytest tests/unit` covers the CloudMetrics config passing, the synthetic multi-hop config passing, and one failing case per rule (unknown key, typo in `access`, missing column, cycle, bad `via`, broken metric SQL, unset env var). `uv run askdb validate-config` exits 0 with the dev env. Ruff is clean.

- [ ] **Slice 2 — Scope builder + read-only executor** (§6.2, §7.2)
  - Files: `src/askdb/scopes/{builder,ids}.py`, `src/askdb/executor.py`, `src/askdb/ddl.py`, `tests/redteam/test_scope_integrity.py`, `tests/redteam/test_executor_attacks.py`, `tests/unit/test_scope_builder.py`, `tests/unit/test_ddl.py`
  - Note (slice 1): open the source DB only via `askdb.config.validate.open_source_readonly`. The synthetic fixture (`tests/fixtures/synthetic/`) already has an orphan order (NULL `account_id`), an unmapped territory (`Isles`) and an unlisted column (`accounts.internal_note`) for the integrity tests.
  - Verify: red-team tests inspect scope files directly (only in-scope rows, no ungranted sensitive columns, multi-hop on the synthetic DB). Executor attacks are all denied: ATTACH, PRAGMA, writes and DDL, multiple statements, `load_extension`, `date('now')`, and a runaway recursive CTE hitting the timeout. The DDL for a restricted scope never contains a dropped column name.

- [ ] **Slice 3 — App DB, auth, grants, Ask page shell** (§2, §3.4, §7.1, §13)
  - Files: `src/askdb/app.py`, `src/askdb/db/{schema,repo}.py`, `src/askdb/auth.py`, `src/askdb/grants.py`, `src/askdb/audit.py`, `src/askdb/templates/{base,login,ask,no_access}.html`, `src/askdb/static/`, `tests/unit/test_auth.py`, `tests/unit/test_grants.py`, `tests/redteam/test_cross_user_scope.py`
  - Verify: `TestClient` tests cover login and logout, CSRF rejection, a must-change-password redirect, the no-grant page, the 127.0.0.1 bind, and that each demo user resolves to the correct scope file. Manual check: `seed-demo`, then `serve`, then log in as the EMEA manager.

- [ ] **Slice 4 — Certified metric, explicit period, answer card** (§5.1, §5.4, §6.1, §6.3, §8.2)
  - Files: `src/askdb/periods.py`, `src/askdb/llm/{client,prompts,schema}.py`, `src/askdb/pipeline.py`, `src/askdb/metrics.py`, `src/askdb/sanity.py`, `src/askdb/format.py`, `src/askdb/templates/answer_card.html`, `tests/unit/test_periods.py`, `tests/unit/test_filters_substitution.py`, `tests/unit/test_metrics_eval_agreement.py`, `tests/unit/test_pipeline_certified.py`
  - Note (slice 1): config validation already expands `{{filters}}` as ` AND <expr> = :f_<name>` (`validate._run_metric_sql`); reuse one substitution function for the pipeline rather than a second copy.
  - Verify: unit tests cover period edges and fiscal start, binding-only `{{filters}}` substitution, and metric/eval agreement (§4.4 list). A fake-LLM pipeline test checks that EMEA and All users get different numbers with correct scope labels. A manual browser check uses the real API.

- [ ] **Slice 5 — Clarify and decline** (§5.1–5.3, §5.5, §8.3)
  - Files: `src/askdb/precheck.py`, `src/askdb/clarify.py`, `src/askdb/value_index.py`, `src/askdb/pipeline.py`, `src/askdb/llm/prompts.py`, `src/askdb/templates/{clarify,refusal}.html`, `tests/ambiguity/test_*.py`, `tests/redteam/test_chip_leakage.py`, `tests/unit/test_value_index.py`
  - Verify: the ambiguity suite (live LLM) covers relative dates with an injected `today`, "recently", past snapshot values, duplicate names, small talk, write requests and injection. The false-confident rate is 0, and declines leave no SQL in the audit log. Clarification options never show out-of-scope values. Fake-LLM unit tests cover the compare logic and chip construction.

- [ ] **Slice 6 — Fallback SQL, comparator, restricted questions, validation suite** (§6.2, §7.4, §8.2, §11.2)
  - Files: `src/askdb/fallback.py`, `src/askdb/compare.py`, `src/askdb/pipeline.py`, `src/askdb/templates/answer_card.html`, `tests/unit/test_compare.py`, `tests/validation/test_eval_set.py`, `tests/ambiguity/test_restricted.py`, `tests/redteam/test_prompt_injection_sql.py`
  - Verify: comparator unit tests cover superset columns, reordered and renamed columns, ORDER BY ties, LIMIT ties and float tolerance. `uv run pytest tests/validation` passes all 28 non-skipped cases and reports 1 skipped. A user without the sensitive grant gets the restriction message.

- [ ] **Slice 7 — Cache, pins, dashboards, metric drift** (§6.4, §9.1, §9.3)
  - Files: `src/askdb/cache.py`, `src/askdb/pins.py`, `src/askdb/drift.py`, `src/askdb/templates/{dashboard,dashboards}.html`, `tests/unit/test_cache.py`, `tests/unit/test_pins.py`, `tests/unit/test_drift.py`, `tests/redteam/test_cache_isolation.py`
  - Verify: users never share cache entries. A pin re-run makes no LLM call. A grant change updates a pin's scope label and value. A changed metric SQL produces the drift notice.

- [ ] **Slice 8 — Scheduled reports + admin console** (§8.4, §9.2, §10)
  - Files: `src/askdb/scheduler.py`, `src/askdb/reports.py`, `src/askdb/admin/{routes,forms}.py`, `src/askdb/templates/admin/*.html`, `src/askdb/templates/reports.html`, `tests/unit/test_scheduler.py`, `tests/unit/test_admin.py`, `tests/redteam/test_scheduled_scope.py`, `tests/redteam/test_admin_authz.py`
  - Verify: a scheduled run produces a snapshot from exactly the user's current scope. Non-admins get 403 on every admin route. Grant edits are audited with a diff and rebuild the scope. Full `uv run pytest` plus lint pass, and the validation, ambiguity and redteam suites are green (§11).
