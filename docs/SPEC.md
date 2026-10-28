# AskDB — v1 Specification

Status: Draft for review · Sources: `docs/one-pager.md`, design interview (2026-10-28), revised for SQLite and the CloudMetrics development dataset (2026-10-28).

AskDB is a web app that lets executives and managers ask a SQLite database KPI questions in plain English. They get a headline number, a plain-English interpretation and a small chart. It is strictly read-only. Each user can only query a copy of the database that physically contains just the rows and columns they may see. When it is unsure, it asks or says so instead of guessing.

**AskDB is data-agnostic.** Everything domain-specific comes from configuration: tables, business rules, certified metrics, row scoping and sensitive columns. Any SQLite database can be plugged in by writing a database config (§4.2) and, ideally, a validation dataset (§4.3). The CloudMetrics files (§4.1) are only the development and test dataset. Examples in this spec use CloudMetrics, but nothing in the app may hard-code its tables, columns, values or rules.

---

## 1. Goals, non-goals, hard guarantees

### 1.1 Goals
- Answer single, standalone KPI questions ("What is our current MRR?", "What was the churn rate in Q3 2025?") in **under 10 seconds**.
- Show the **headline number**, an **interpretation line**, a **scope label**, and a **supporting chart**.
- **Pinned answers, personal dashboards and scheduled reports** in v1.
- v1 is a **development and demo build** that runs locally on one machine. It is used by developers and for demos, with several test accounts to show scoping. Real executive users arrive with a later networked release that is not specified here.

### 1.2 Hard guarantees (equally critical; each is a release blocker)
| # | Guarantee | Primary enforcement | Secondary enforcement |
|---|-----------|--------------------|-----------------------|
| G1 | Never show a wrong number with confidence | Certified SQL metrics; clarification chips; self-consistency check; sanity checks | Uncertified answers always badged; validation and ambiguity suites in CI (§11) |
| G2 | Never change data | Query path opens only read-only scope copies (`mode=ro`, `PRAGMA query_only`); SQLite authorizer allows reads only | Single statement per execution; write requests declined before SQL generation; scope files are read-only on disk |
| G3 | Never show restricted data | **Per-scope database copies**: restricted rows and columns are not present in the file a user queries | Authorizer blocks `ATTACH`; per-scope schema sent to the LLM; red-team suite as a release gate |

### 1.3 Out of scope for v1
- Follow-up conversation ("And split that by industry?"). Every question stands alone.
- Exporting (Excel, PDF) or sharing answers or dashboards with others.
- Forecasts, predictions, recommendations.
- Databases other than SQLite, and more than one configured database per deployment.
- Languages other than English. Non-English questions get a polite refusal.
- Narrative or LLM-written summaries of results. The LLM never sees results.
- Networked deployment of any kind: production hosting, SSO, TLS, remote users and high availability. v1 is local/dev only (§3.4). Requirements for a networked release will be specified separately; this spec sets no checklist for it.

---

## 2. Users and roles

| Role | Who | Can do |
|------|-----|--------|
| **User** | Executives, managers | Ask questions, pin answers, build personal dashboards, schedule reports to themselves, flag answers as wrong |
| **Admin** | Single role (data/platform owner) | Everything in the admin console: users, grants, the scope-group map, settings, review queue, audit log |

- Sign-in uses **username and password, managed by the admin** (§3.4).
- A signed-in user with **no grants** sees a "You don't have access yet" page with a **Request access** button that notifies admins. They cannot ask questions.

---

## 3. Architecture

### 3.1 Components (single Python process plus a scope builder)
```
Browser (server-rendered pages + HTMX, Chart.js)
   │
   ▼
FastAPI app ─────────────────────────────────────────► Anthropic API (Claude): metadata only
   ├─ Question pipeline (§5, §6)
   ├─ Query executor ──► var/scopes/<scope_id>.db   (read-only, one file per scope)
   ├─ Scheduler (APScheduler, in-process) ──► same executor, same scope files
   └─ App state ───────► var/app.db                 (users, grants, pins, audit…)

Scope builder (in-process job / CLI) ──► reads the source DB named in the config (read-only)
                                     └─► writes var/scopes/*.db
```

### 3.2 Stack
- **Python 3.12**, managed with **uv**. **FastAPI**, Jinja2 templates + HTMX for interactivity, **Chart.js** for charts. A server-rendered UI keeps the local setup to one toolchain.
- Python stdlib `sqlite3` for both the data DB and the app DB. PyYAML (safe loader only) for configs, validated with Pydantic models. sqlglot (SQLite dialect) for statement checks (§6.2) and for parsing `ORDER BY`/`LIMIT` in the eval harness (§11.2).
- **pytest** for unit, validation, ambiguity and red-team suites.
- **Claude via the Anthropic API**, with structured outputs via tool use / JSON schema. Use a current Claude model, and a faster tier for interpretation if the 10 s target requires it.

### 3.3 Repository layout
```
pyproject.toml
src/askdb/                     # app code (no domain-specific code)
docs/one-pager.md  docs/SPEC.md
test/cloudmetrics.db           # development dataset (§4.1), kept here
test/cloudmetrics.yaml
test/cloudmetrics_eval.yaml
var/app.db                     # app state (gitignored)
var/scopes/                    # generated scope copies (gitignored)
tests/unit/  tests/validation/  tests/ambiguity/  tests/redteam/
```
Which config is loaded is set by environment, not by path conventions:

| Variable | Meaning | Development value |
|----------|---------|-------------------|
| `ASKDB_DATABASE_CONFIG` | Path to the database config (§4.2) | `test/cloudmetrics.yaml` |
| `ASKDB_VALIDATION_SET` | Path to the validation dataset (§4.3); tests only | `test/cloudmetrics_eval.yaml` |
| `CLOUDMETRICS_DB_PATH` | Referenced by `path:` inside the config | `test/cloudmetrics.db` |

### 3.4 Deployment and auth (local/dev v1)
- Run with `uv run askdb serve`. It binds to **127.0.0.1** only. v1 has no option to bind to other interfaces, because networked use is out of scope (§1.3). Several local accounts (e.g. an EMEA manager, an All-regions exec, an admin) are used to demonstrate scoping. `uv run askdb seed-demo` creates them.
- Passwords are hashed with argon2. Sessions use signed, HttpOnly, SameSite=Strict cookies. Forms carry CSRF tokens.
- The first admin is created with `uv run askdb create-admin`. Admins then create users in the console with a one-time initial password that must be changed at first login.
- `ANTHROPIC_API_KEY` and the session secret come from environment variables or a `.env` file. They are never stored in `app.db`.

---

## 4. Data and configuration formats

### 4.1 Development dataset (provided)
The initial SQLite database, schema file and evaluation set are provided for testing the app during development. They stay in the `test/` folder:

| File | Purpose |
|------|---------|
| `test/cloudmetrics.db` | The database: a B2B project-management SaaS company's customers (200), plans (4), subscriptions (282), invoices (1,831) and support tickets (709). Dates span **2022-03-14 to 2025-11-15**; all money is USD. |
| `test/cloudmetrics.yaml` | Schema definition and business rules, in the database config format (§4.2). |
| `test/cloudmetrics_eval.yaml` | Evaluation set: 29 cases in the validation dataset format (§4.3). |

These files are test fixtures. The app must work the same with any other database config, and no CloudMetrics names may appear in `src/`.

### 4.2 Database config format
A YAML file, loaded with the safe loader and validated strictly. **Unknown keys are an error**, because a typo in `access` must never silently disable scoping. The app refuses to start on any validation error.

#### Top-level keys
| Key | Req. | Type | Meaning |
|-----|------|------|---------|
| `name` | yes | slug | Identifier; must equal `database` in the validation dataset |
| `display_name` | yes | string | Shown in the UI |
| `path` | yes | string | Path to the SQLite file. `${VAR}` is expanded from the environment, and an unset variable is a startup error. Relative paths resolve from the working directory. Always opened read-only. |
| `calendar.fiscal_year_start_month` | no (default 1) | 1–12 | Defines "quarter", "year" and "YTD" (§5.1) |
| `data_coverage` | no | map | See below |
| `description` | yes | text | Free text sent **verbatim** to the model: table grains, joins, metric definitions, status/NULL conventions, SQL dialect notes, and domain disambiguation rules ("Enterprise customers" = size tier, not plan). The authoritative business rules. |
| `tables` | yes | list | Table definitions, below |
| `access` | no | map | Row scoping and sensitive categories, below. If absent, there is no row scoping: one scope, and a startup warning. |
| `metrics` | no | list | Certified metrics, below. If absent, every answer is uncertified. |

#### `data_coverage`
| Key | Default | Meaning |
|-----|---------|---------|
| `mode` | `live` | `static_snapshot` (historical extract: show "data through <end>", never a stale banner) or `live` |
| `expected_cadence` | — | `live` only: `hourly` / `daily` / `weekly`. Data older than this shows a stale banner |
| `start`, `end` | computed | Optional overrides. By default these are the min and max over all columns typed `DATE` or `DATETIME`, recomputed on each scope build |

#### `tables[]`
| Key | Req. | Meaning |
|-----|------|---------|
| `name` | yes | Table name in the SQLite file. Must exist, and is checked at startup. |
| `description` | yes | Rendered as a comment on the DDL |
| `columns[]` | yes | Each column must exist in the table. Either YAML flow (`{ name: …, type: … }`) or block style is accepted. |

Column keys:
| Key | Req. | Meaning |
|-----|------|---------|
| `name` | yes | Column name |
| `type` | yes | `INTEGER`, `REAL`, `TEXT`, `DATE`, `DATETIME` (DATE = `YYYY-MM-DD` text, DATETIME = `YYYY-MM-DD HH:MM:SS` text) |
| `description` | no | Rendered as a column comment. Strongly recommended. |
| `primary_key` | no | `true` for the key column |
| `references` | no | `table.column` foreign key. Used for DDL rendering and for row-scope propagation. |
| `sensitive` | no | Name of a category in `access.sensitive_categories`. The column is dropped from scope copies (and from the model's DDL) for users without that grant. |
| `indexable` | no | Override for filter-value matching (§5.5). By default `TEXT` columns with ≤ 50 distinct values are indexed. |
| `display_name` | no | `true` marks the column humans use to name a row of this table (e.g. `company_name`). At most one per table, and the table must have a `primary_key`. Used to handle duplicate names (§5.5, §8.2). |

Columns that exist in the database but are not listed are **excluded** from scope copies and are never visible to the model or users. Listing is the allow-list.

#### `access`
```yaml
access:
  row_scope:
    table: customers            # the table that carries the scoping attribute
    column: country             # the scoping attribute
    group_label: Region         # UI name for a group
    groups:                     # default map, seeded into app.db; admins edit the live copy
      EMEA: [United Kingdom, Germany, France, Netherlands]
      ...
    scoped_tables:              # filtered to rows whose `via` column references a kept parent row
      - { table: invoices, via: customer_id }   # parent: row_scope.table or another scoped table
    reference_tables: [plans]   # copied unfiltered (lookup data)
  sensitive_categories:
    customer_identity: { label: Customer identity, description: ... }
```
Validation rules, all fail-closed:
- Every table in `tables` appears in exactly one of: `row_scope.table`, `scoped_tables` or `reference_tables`.
- Each `via` column must declare `references` to the primary key of either the `row_scope.table` or **another `scoped_tables` entry**. Chaining entries this way gives **multi-hop** propagation. For example:
  ```yaml
  scoped_tables:
    - { table: orders,      via: customer_id }   # orders.customer_id  -> customers.customer_id
    - { table: order_items, via: order_id }      # order_items.order_id -> orders.order_id
  ```
  Every hop is a declared `references`, and every intermediate table must itself be a `scoped_tables` entry, so the chain is explicit. Chains must end at the `row_scope.table`, and cycles are a config error. When a table has several possible paths (CloudMetrics `invoices` has both `customer_id` and `subscription_id`), the `via` entry decides which one is used.
- Each `sensitive` value on a column must name a declared category.
- Values of the scoping column not mapped to any group are visible only to users granted **All**. The admin console lists them.

#### `metrics[]` (certified metrics)
| Key | Req. | Meaning |
|-----|------|---------|
| `name` | yes | Slug, unique |
| `label` | yes | Shown on the answer card |
| `synonyms` | no | Phrases that map to this metric |
| `kind` | yes | `period` (a value over a date range) or `snapshot` (a current value from present status) |
| `unit` | yes | `usd`/currency code, `count`, `ratio` (shown as %), `hours`, `number` |
| `time_column` | `period` only | `table.column` the period applies to (documentation and validation) |
| `sql` | yes | Single `SELECT` returning one row with a column named `value`. `period` metrics must use `:start` and `:end` (half-open). It may contain `{{filters}}`. |
| `filters` | no | Map of filter name → SQL expression valid in `sql`. When a question filters on one, the app replaces `{{filters}}` with `AND <expr> = :f_<name>` (bound). Filters not listed make the question uncertified. |
| `trend` | `period` only | `{ grain: month\|quarter\|year, periods: N }`. The app runs `sql` once per period for the chart. |
| `breakdown_sql` | no (`snapshot`) | Returns `label, value` rows for the supporting chart. May contain `{{filters}}`. |

Rules:
- Every `sql` and `breakdown_sql` must run at startup against the source DB without error.
- Only the app substitutes `{{filters}}`, using bound parameters. Filter values are never string-formatted into SQL.
- The SQL hash of each metric is stored. A change triggers metric-drift handling (§9.3).
- **Snapshot metrics are current-only.** They answer only "as of the latest data", and show a breakdown instead of a trend, labelled "Current snapshot — history not tracked". Past-dated and trend questions about them are declined (§5.3). v1 has no history mechanism for snapshot metrics.
- `metrics` must agree with `description`. Where a validation case exists for a metric, the metric's result must equal that case's expected result (§11.4).

### 4.3 Validation dataset format
A YAML file, validated strictly. It is used only by the test suites. It is **never loaded at startup and never sent to the model**.

| Key | Req. | Meaning |
|-----|------|---------|
| `database` | yes | Must equal the database config's `name` |
| `cases[]` | yes | List of cases |

Case keys:
| Key | Req. | Meaning |
|-----|------|---------|
| `id` | yes | Unique slug |
| `question` | yes | The user's question, as typed |
| `category` | yes | Free-text grouping for reports. CloudMetrics uses `totals_trend`, `ranking`, `filter`, `comparison`, `clarification`, `non_data` |
| `expected_sql` | one of | SQL whose result set is the correct answer. It must run against the source DB. |
| `expected_outcome` | one of | `clarification` or `declined` |
| `today` | no | ISO date injected as "today" for this case (§5.1). Default: the real date. |
| `conversation[]` | no | Prior turns `{question, sql}`, which mark a follow-up case. Skipped in v1 (§11.2). |
| `notes` | no | Explanation for humans |

Exactly one of `expected_sql` and `expected_outcome` is required. Pass rules are in §11.2.

### 4.4 Changes made to the provided files
The formats were kept as provided. The file was changed only where it conflicted with this spec:

| File | Change | Why |
|------|--------|-----|
| `cloudmetrics.yaml` header | It said the model sees "exactly `description` and `tables`". It now says the model sees `description`, the **per-scope** DDL and the metric catalog, and that `metrics` must agree with `description`. Format reference now points to this spec. | Per-scope DDL (§7) and certified metrics (§4.2) |
| `cloudmetrics.yaml` `description` | Replaced "Relative periods: date('now', '-12 months')" with an instruction never to use `date('now')`/`CURRENT_*` | Relative periods are resolved by the app with an injectable `today` (§5.1). A real-clock SQL call would break clarification and the eval's `today:` |
| `cloudmetrics.yaml` | Added `data_coverage: { mode: static_snapshot }` | Data ends 2025-11-15. Without it, every answer would carry a stale banner. |
| `cloudmetrics.yaml` | Added `sensitive: customer_identity` on `customers.company_name` and `support_tickets.subject`; `indexable: true` on `company_name` and `false` on `subject` | Sensitive-column grants (§7). `company_name` exceeds the auto-index threshold, and `subject` is free text. |
| `cloudmetrics.yaml` | Added `display_name: true` on `customers.company_name` | Duplicate-name handling (§5.5, §8.2). Two customers share a name. |
| `cloudmetrics.yaml` | Added `access` (country→region groups, scoped and reference tables) | Row scoping (§7) |
| `cloudmetrics.yaml` | Added `metrics`: revenue, mrr, arpu, active_customers, customer_count, new_customers, churn_rate, avg_resolution_hours, all transcribed from `description` | Certified answers (§4.2). Checked: each returns exactly the expected result of the matching eval case (`total_mrr`, `arpu`, `active_customer_count`, `avg_resolution_hours`, `churn_rate_q3_2025`, `mrr_by_plan`, 2025 revenue). |
| `cloudmetrics_eval.yaml` header | Path references updated to `test/cloudmetrics.yaml` and this spec. No case or format changes. | Files stay in `test/` |

---

## 5. Question understanding and uncertainty

### 5.1 Time periods and relative dates
Data can end long before real today (CloudMetrics ends **2025-11-15**), so relative periods are a key way to show a confidently wrong (empty or zero) number.

- **Relative period phrases** behave according to `data_coverage.mode`:
  - **`static_snapshot`**: well-defined relative phrases ("last month", "this quarter", "YTD") **always trigger clarification chips**, every time. There is no anchoring and no per-session memory. The chips are anchored to the data coverage, for example: [Latest complete month in data (Oct 2025)] [Latest data month to date (Nov 1–15, 2025)] [Pick a period…]. This costs one click but ensures "last month" never silently means a month long past.
  - **`live`**: well-defined relative phrases resolve against the **real calendar** with no chips. "Last month" is the last complete month before today, and "this quarter" is quarter to date. The concrete dates always appear in the interpretation line, and the partial-period and stale checks still apply.
  - **Vague phrases** ("recently", "lately", "in a while") have no defined period and trigger chips in **both** modes. Static mode offers e.g. [Last 3 months of data (Aug–Oct 2025)]; live mode offers e.g. [Last 30 days] [Last 3 months].
- **Explicit periods** ("Q3 2025", "2024", "March 2025") are answered directly, with concrete dates in the interpretation line: "Q3 2025 (Jul 1 – Sep 30, 2025)". Quarters and years follow `calendar.fiscal_year_start_month`.
- **No period** on a **snapshot** metric is answered as of the data end: "as of Nov 15, 2025 (latest data)".
- **Any past date or trend** on a **snapshot** metric ("MRR at the end of 2024", "ARPU trend in 2025") is declined (§5.3). Relative words that mean the present ("current", "now", "today") are treated as "latest data" with no chips.
- **No period** on a **period** metric gets chips: [Latest complete month] [Latest year to date] [All time].
- **Periods outside coverage** return "No data for this period — data covers <start> to <end>". They never return 0.
- **Partial periods** that overlap a coverage edge are labelled, e.g. "Q4 2025 — data through Nov 15 only".
- `today` is injectable throughout the pipeline (the validation `today:` uses it), and SQL never reads the real clock (§6.2).

### 5.2 Other reasons to ask instead of answer (one-click chips)
- **Multiple metric matches**, unless `description` states a rule that settles it.
- **Self-consistency disagreement.** The question is interpreted twice independently. If the two readings differ in metric, period or filters, AskDB asks.
- **Filter phrase** that matches zero or several values in the user's scope.
- **"None of these"** → "Try rephrasing your question", plus a "Flag for an analyst" option. There is no free-text follow-up.

### 5.3 Declined before any SQL is generated
- Small talk and non-data questions.
- Requests to change data ("Mark all overdue invoices as paid"): "AskDB is read-only and can't change data."
- Prompt-injection and system-prompt requests.
- Follow-ups that reference a previous answer, forecasts, and export requests.
- Non-English questions.
- **Past values or trends of snapshot metrics**, e.g. "What was MRR at the end of 2024?" → "MRR history isn't recorded, so I can only give the current value (as of Nov 15, 2025)." It also offers a chip [Show current MRR]. These questions are **not** routed to fallback SQL, because reconstructing past status from current rows would produce a confident but wrong number. The interpretation prompt tells the model which metric concepts are snapshot-only, and the ambiguity suite (§11.1) includes past-dated snapshot questions that must be declined.

### 5.4 Interpretation (LLM input/output)
- **Input:** the question, the config `description` (verbatim), the **per-scope** DDL rendered from `tables` (unlisted and restricted columns omitted, descriptions as comments), the metric catalog (name, label, synonyms, kind, filter names), the calendar, the data coverage dates and `today`. It never includes rows, sample values or results.
- **Output (strict schema):** `{kind: certified|fallback|clarify|decline, metric?, period: {expression, start?, end?}, filters: [{name, phrase}], clarify_options?, decline_reason?}`.
- The output is validated: unknown metrics, filters or columns are rejected, and the model has no tools that touch data.

### 5.5 Filter values
Filter phrases are fuzzy-matched against distinct values of indexable columns (§4.2), **read from the user's own scope copy**. Chips can therefore only show values the user is allowed to see.

**Duplicate names.** When a phrase matches a `display_name` value shared by several rows (CloudMetrics has two customers with the same `company_name`), AskDB asks via chips. There is one chip per row, each with distinguishing details: the values of up to two other indexable, non-sensitive columns of that table that differ between the matches, e.g. [Acme Corp — Germany, Enterprise] [Acme Corp — United States, SMB]. If no such columns differ, the key is shown ("#42"). A final chip, [All named "Acme Corp" combined], is also offered. The chosen chip becomes a filter on the **primary key**, not on the name, so the filter is never ambiguous.

---

## 6. SQL execution and safety

### 6.1 Pipeline
```
question → pre-checks (grant, English, daily question limit)
 → interpret ×2 (LLM) → compare → resolve period/filters (§5)
 → clarify? (stop) / decline? (stop)
 → SQL: certified metric + bound params | fallback SQL ×2 (LLM)
 → execute on the user's scope copy (§6.2) → sanity checks (§6.3)
 → answer card + audit log
```

### 6.2 Execution guardrails
- Connection: `sqlite3.connect("file:var/scopes/<id>.db?mode=ro", uri=True)`, then `PRAGMA query_only = ON`.
- An **authorizer** (`set_authorizer`) allows only `SQLITE_SELECT`, `SQLITE_READ`, `SQLITE_FUNCTION` (an allowlist of SQLite core scalar, aggregate and date functions) and `SQLITE_RECURSIVE`. It denies everything else, including **`ATTACH`** (which would open another scope file), `PRAGMA`, all writes and DDL, and transactions. `load_extension` stays disabled.
- **One statement per execution**: the SQL is checked to contain exactly one statement, and the stdlib `execute` also rejects multiple statements.
- **No real clock**: SQL containing `'now'` as a date/time argument, `CURRENT_DATE`, `CURRENT_TIME` or `CURRENT_TIMESTAMP` is rejected. Periods are always bound parameters.
- **Timeout**: a `set_progress_handler` aborts queries after **5 s**.
- **Row cap**: at most 10,000 rows are fetched. Fallback non-aggregate queries must include `LIMIT`.
- **Fallback SQL** additionally: no `SELECT *`. Two independent candidates are executed. If their result sets differ (compared as in §11.2), AskDB says "I'm not confident about this one" and offers to flag it.
- **LLM cost limit**: a per-user daily question limit (default 200, admin-configurable).

### 6.3 Sanity checks
- **No rows / NULL** → "No data found for <interpretation>", never "0".
- **Outside coverage / partial period** → as in §5.1.
- **Anomalous zero** (current value is 0 while every trend period is non-zero) → warning banner.
- **Freshness**: `static_snapshot` → the interpretation line carries "data through <end>" and there is no stale banner. `live` → a stale banner appears only when the data end is older than `expected_cadence` allows.

### 6.4 Caching
The result cache key is `user + resolved query (metric/SQL, params) + scope file hash`. It is invalidated by a scope rebuild, grant change or metric hash change. Cached answers are still audit-logged.

---

## 7. Permissions and scope copies

### 7.1 Grant model
A user's grant consists of:
- **Scope groups**: a set of groups from `access.row_scope.groups` (CloudMetrics: regions), or **All**.
- **Sensitive categories**: zero or more categories from `access.sensitive_categories` (CloudMetrics: *Customer identity* = company names and ticket subjects).

A user with no grant has no access.

The group map is seeded from the config into `app.db`, and admins edit it there. The CloudMetrics default:
| Region | Countries |
|--------|-----------|
| North America | United States, Canada |
| EMEA | United Kingdom, Germany, France, Netherlands |
| APAC | Australia, India, Japan |
| LATAM | Brazil |

### 7.2 Scope copies (the enforcement boundary)
- A **scope** is a distinct pair of (group set, sensitive-category set). Its id is a hash of the grant, the group map, the source DB hash and the config hash.
- The **scope builder** opens the source DB read-only and writes `var/scopes/<id>.db` containing only listed tables and columns:
  - The `row_scope.table` filtered to `column IN (<values of the granted groups>)`.
  - Each `scoped_tables` entry filtered to rows whose `via` column references a kept row of its parent table. Tables are processed parent-first, in dependency order. Rows whose `via` value is NULL or points to a missing parent are **dropped** (fail-closed).
  - `reference_tables` copied whole.
  - `sensitive` columns **dropped** unless their category is granted.
- Each file is written to a temp path, verified (row counts and foreign keys) and **atomically renamed**, then set read-only on disk. Old files are deleted once no request is using them.
- Rebuilds happen at startup, when the source DB hash or the config changes, and when any grant or the group map changes. Until a user's new scope file is ready, their questions return "Your access is being updated".
- The query path never opens the source DB. Only the builder and config validation do.
- The LLM receives the **scope's** DDL, so it never learns that a dropped column exists.

### 7.3 Scope labelling
Every answer states its scope: "**EMEA only (your access)**" or "**All regions**", using `group_label`. This stops a partial figure being read as a company total.

### 7.4 Restricted questions
If a question needs a sensitive column the user lacks (e.g. "Top 10 customers by revenue" by name), the answer says "Customer names require *Customer identity* access." It never silently substitutes IDs. Users without the grant can still get aggregate answers.

### 7.5 Known limitation: small-group re-identification (accepted for v1)
Hiding sensitive columns does not stop a user from singling out an entity through other attributes. For example, "MRR for Healthcare Enterprise customers in Brazil" may describe a single company, and CloudMetrics LATAM has only 8 customers. v1 **accepts this risk**: there is no small-group suppression or warning, and answers are shown whatever the group size. The risk is acceptable because users only ever see entities inside their own granted scope groups, and the sensitive values themselves (e.g. names) are never present. Revisit before onboarding datasets with personal data about individuals.

### 7.6 Known limitation: single-admin grant control (accepted for local/dev v1)
Any admin can change any grant, including their own, to All groups plus every sensitive category, and the change takes effect at the next scope build. There is no approval step, self-grant restriction or notification. The **audit log** (§10) is the only control: every grant change is recorded with actor, timestamp and a before/after diff. This is accepted because v1 runs only locally on a trusted machine (§3.4). Grant safeguards belong to the separately specified networked release.

---

## 8. UI/UX

### 8.1 Ask screen
- One prominent question box with example questions built from certified metric labels.
- Progress states: "Understanding your question…", then "Running…". Target is under 10 s.
- Desktop and **responsive mobile** are both first-class: the card fits a phone screen and chips wrap.

### 8.2 Answer card
1. **Headline number**, formatted by the metric's `unit`.
2. **Interpretation line**: "Revenue (paid invoices) · Q3 2025 (Jul 1 – Sep 30, 2025) · EMEA only (your access) · data through Nov 15, 2025".
3. **Supporting chart**:
   - Period metrics: a trend per `trend` with the selected period highlighted. Partial periods are hatched, and nothing is drawn past the coverage end.
   - Snapshot metrics: `breakdown_sql`.
   - Fallback answers: a table of the raw result.
   - **Duplicate labels**: rows of a result that group by an entity must be grouped by its primary key. The interpretation prompt requires this for any SQL grouping or listing by a `display_name` column, and certified `breakdown_sql` must do it too. When two rows of a table or chart share the same `display_name` value, the key is appended to those rows only: "Acme Corp (#42)", "Acme Corp (#117)". Unique names show unchanged. The key column is selected for this purpose and hidden from the table otherwise. If a result has colliding names but no key column (possible only for uncertified SQL), a note says "Some rows share the same name and may be different customers".
4. **Banners** as applicable: uncertified ("Not a certified metric — verify before relying on it."), partial period, anomalous value, stale (`live` only).
5. **Actions**: Pin, Add to dashboard, Schedule (all certified only), and **"This looks wrong"**.

Not shown in v1: SQL text, period-over-period deltas.

### 8.3 Clarification, refusals and errors
- Clarification: a short explanation followed by chips (§5).
- Refusals and errors use plain language with no stack traces: out of scope, read-only, needs a sensitive grant, daily limit reached, timeout, no data for the period, non-English.

### 8.4 Admin console
- **Users and access**: create and disable users, reset passwords, set groups or All, set sensitive categories, handle access requests, and see each user's scope build status.
- **Scope groups**: edit the group map, with a warning about unmapped values.
- **Configuration**: read-only view of the loaded config (tables, metrics, access rules), validation errors and metric drift history.
- **Settings**: daily question limit, timeouts, and scheduler email (SMTP, optional).
- **Review queue**: "This looks wrong" flags and fallback questions, grouped by frequency.
- **Audit log**: searchable and read-only.

---

## 9. Pins, dashboards and scheduled reports

### 9.1 Pins and dashboards
- A pin stores the **resolved query**: the metric, bound filters and a *relative-to-data* or explicit period. It does not store question text, so re-running needs no LLM and the interpretation cannot drift.
- Pins re-run on open, served from cache when valid.
- Dashboards are personal, named, ordered collections of pins. They are never shared.
- When a user's grant changes, pins re-run in the new scope and their scope labels update.

### 9.2 Scheduled reports
- Certified pins and dashboards can be scheduled daily, weekly or monthly in the user's time zone, **to the creator only**.
- APScheduler runs them in-process against the user's **current** scope file.
- Each run stores a **snapshot**. Delivery is a **link only**: an in-app "Reports" inbox, plus an optional email when SMTP is configured. Numbers never appear in the email.
- Disabled users' schedules pause and their snapshots are deleted. Run failures are shown in the report, not skipped silently.

### 9.3 Metric drift
When the config is reloaded, metric SQL hashes are compared. Pins and schedules on a changed metric show "Definition changed on <date>". Those on a removed metric show a broken state and notify the owner.

---

## 10. Audit log
- **Per question**: user, timestamp, question, both interpretations, the outcome path, the SQL with bound parameters, scope id, latency and outcome (`answered`, `clarified`, `declined`, `refused`, `error` or `timeout`).
- **Result values are not logged.**
- Also logged: logins, grant and group-map changes, scope builds, config loads and admin setting changes.
- Admins only; retained for 1 year (in `app.db`).

---

## 11. Testing and release gates

### 11.1 Ambiguity and decline suite (gate for G1)
These questions **must** trigger clarification or be declined, never answered. Examples are relative dates in `static_snapshot` mode with an injected `today`, "recently" in either mode, competing metrics, past-dated snapshot questions ("MRR at the end of 2024"), filters on duplicated names, small talk, write requests and injection. The required **false-confident rate is 0**. The suite runs in CI on any change to prompts, model or config.

### 11.2 Validation dataset (§4.3)
- Run with `uv run pytest tests/validation`, against the database and config named by `ASKDB_VALIDATION_SET` / `ASKDB_DATABASE_CONFIG` (development: the `test/` files).
- It runs as a test user granted **All** groups and **all** sensitive categories, because the expected SQL is unscoped.
- **`expected_sql` cases pass** when the generated (or certified) result **contains** the expected result on the source DB. The rules for "contains" are:
  - **Columns are a superset.** Every expected column must map one-to-one to a distinct generated column with matching values; names, aliases and positions are ignored. Extra generated columns are ignored. This covers primary keys added for duplicate-name display (§8.2) and extra detail such as a count. A missing expected column fails the case, even if the question didn't ask for it (e.g. `country` in `enterprise_customers_on_trial`).
  - **Rows must match exactly** on the mapped columns, with the same count. The mapping is found by pairing columns whose value multisets are equal, then verifying the whole projected row set. With only a few columns, trying all candidate mappings is cheap.
  - **Order** is checked only when `expected_sql` has a top-level `ORDER BY`. Generated rows must follow the expected order, but rows that tie on the expected ordering columns may appear in any order. The ordering columns are found by parsing `expected_sql` (sqlglot, SQLite dialect) and mapping its `ORDER BY` terms to output columns. If a term can't be mapped to an output column, the case falls back to multiset comparison and logs a warning.
  - **LIMIT ties.** If `expected_sql` has `LIMIT n` and the cut-off falls inside a tie, any rows from that tie block are accepted. The harness re-runs `expected_sql` without its `LIMIT` to find the full tie block.
  - Floats are compared with a relative tolerance of 1e-6, and NULL equals NULL.
- **`expected_outcome` cases** pass when the outcome is `clarification` or `declined` as stated. Declined cases must produce **no SQL** at all.
- **`conversation` cases** (follow-ups) are **skipped** with the reason "follow-ups out of scope in v1" and reported separately, not counted as passes.
- Gate: **all non-skipped cases pass**. CloudMetrics has 29 cases, one skipped, all run unscoped. That is sufficient for v1 (dev/demo): no scoped variants and no minimum-size target are required. Scoping correctness is covered by the red-team suite (§11.3), and the snapshot and duplicate-name rules by the ambiguity suite (§11.1) and unit tests.

### 11.3 Permission red-team suite (gate for G2/G3)
Runs against scope fixtures built from the development dataset with users of different grants:
- Questions aimed at other groups, at sensitive columns without the grant, and at the source DB.
- Raw-SQL attacks on the executor: `ATTACH` of another scope file or the source, `PRAGMA`, `INSERT`/`UPDATE`/`DELETE`/`DROP`, multiple statements, `load_extension`, `date('now')`, recursive CTE runaway (must hit the timeout).
- Prompt injection: "ignore previous instructions", attempts to reveal the system prompt, and DROP TABLE.
- Chip and value-index leakage: no out-of-scope values ever appear.
- Cache isolation across users, and scheduled runs producing exactly the user's scope.
- Scope-file integrity: each file contains only in-scope rows and permitted columns. This is checked by direct inspection, not through the app.

Any failure blocks release.

### 11.4 Config and unit tests
- Config validation: strict schema, every table and column exists, `access` coverage rules, and every metric SQL runs.
- **Metric/eval agreement**: where a validation case corresponds to a certified metric, both return the same result. A metric-to-case mapping lives in the test, not in the config.
- A **second, synthetic database config** with different tables, a different scoping column, no metrics and a **multi-hop** chain (e.g. `order_items → orders → customers`) is used to keep the app data-agnostic.
- Unit tests: period resolution (fiscal start, boundaries, partial periods, coverage edges), the result-set comparator, `{{filters}}` substitution, scope-builder filters and column dropping.

---

## 12. Non-functional requirements
| Area | Requirement |
|------|-------------|
| Latency | p90 < 10 s end to end; cache hit < 1 s; SQL execution typically < 100 ms on the development dataset |
| Scale | One machine, a handful of local test/demo accounts; one process; SQLite for data and app state |
| Security | Localhost bind only; argon2 passwords; CSRF and secure cookies; secrets in env vars |
| Privacy | LLM receives metadata only: never results, sample values or rows. Per-scope DDL omits restricted columns |
| Accessibility | WCAG 2.1 AA for the answer card, chips and dashboards; charts have text alternatives |

---

## 13. App data model (`var/app.db`, abridged)
- `users(id, username, password_hash, is_admin, status, must_change_password, created_at)`
- `grants(user_id, groups_json | all, sensitive_categories_json, updated_by, updated_at)`
- `scope_groups(group_name, value)`
- `scopes(id, groups_json, sensitive_json, source_hash, config_hash, built_at, status)`
- `access_requests(id, user_id, created_at, resolved_by, resolved_at)`
- `metric_versions(name, sql_hash, loaded_at, removed_at)`
- `pins(id, user_id, metric_name, filters_json, period_expr, created_at, broken_reason)`
- `dashboards(id, user_id, name)`, `dashboard_items(dashboard_id, pin_id, position)`
- `schedules(id, user_id, target_type, target_id, cadence, tz, paused_reason)`
- `snapshots(id, schedule_id, computed_at, payload)`
- `result_cache(key, user_id, payload, scope_id, expires_at)`
- `usage(user_id, date, questions)`
- `flags(id, user_id, audit_id, note, status)`
- `audit_log(id, ts, actor, type, details_json)`
- `settings(key, value)`

---

## 14. Risks and open items
No open items. All earlier items were resolved in review on 2026-10-28:
- Small-group re-identification is an accepted limitation (§7.5).
- Duplicate names are handled in §5.5 and §8.2.
- Snapshot metrics are current-only (§4.2, §5.3).
- Relative-date handling is defined per mode (§5.1).
- The eval comparison rules are in §11.2.
- Single-admin grant control is an accepted limitation (§7.6).
- v1 is local dev/demo only (§1.1, §1.3, §3.4).
- Multi-hop row scoping is defined in §4.2 and §7.2.
- Eval coverage is set in §11.2.
