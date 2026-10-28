"""One failing case per config validation rule (SPEC 4.2, 11.4). All fail closed."""

from __future__ import annotations

from typing import Any

import pytest

from askdb.config import ConfigError, load_config, parse_config, validate_config
from tests.conftest import CLOUDMETRICS_CONFIG


def errors_for(raw: dict[str, Any]) -> str:
    with pytest.raises(ConfigError) as exc:
        validate_config(parse_config(raw))
    return str(exc.value)


def table(raw: dict[str, Any], name: str) -> dict[str, Any]:
    return next(t for t in raw["tables"] if t["name"] == name)


def column(raw: dict[str, Any], tname: str, cname: str) -> dict[str, Any]:
    return next(c for c in table(raw, tname)["columns"] if c["name"] == cname)


def metric(raw: dict[str, Any], name: str) -> dict[str, Any]:
    return next(m for m in raw["metrics"] if m["name"] == name)


# --- strict schema ---------------------------------------------------------------


def test_unknown_top_level_key(cloudmetrics_raw):
    cloudmetrics_raw["descripton"] = "typo"
    assert "descripton: unknown key" in errors_for(cloudmetrics_raw)


def test_typo_in_access_is_an_error(cloudmetrics_raw):
    rs = cloudmetrics_raw["access"]["row_scope"]
    rs["scoped_table"] = rs.pop("scoped_tables")
    assert "access.row_scope.scoped_table: unknown key" in errors_for(cloudmetrics_raw)


def test_unknown_column_key(cloudmetrics_raw):
    column(cloudmetrics_raw, "customers", "company_name")["sensitve"] = "customer_identity"
    assert "sensitve: unknown key" in errors_for(cloudmetrics_raw)


def test_bad_column_type(cloudmetrics_raw):
    column(cloudmetrics_raw, "plans", "monthly_price")["type"] = "FLOAT"
    assert "tables.1.columns.2.type" in errors_for(cloudmetrics_raw)


def test_non_bool_flag_is_rejected(cloudmetrics_raw):
    column(cloudmetrics_raw, "plans", "plan_id")["primary_key"] = "yes"
    assert "primary_key" in errors_for(cloudmetrics_raw)


def test_fiscal_month_out_of_range(cloudmetrics_raw):
    cloudmetrics_raw["calendar"]["fiscal_year_start_month"] = 13
    assert "fiscal_year_start_month" in errors_for(cloudmetrics_raw)


def test_missing_required_key(cloudmetrics_raw):
    del cloudmetrics_raw["description"]
    assert "description: Field required" in errors_for(cloudmetrics_raw)


# --- path ------------------------------------------------------------------------


def test_unset_env_var_in_path(cloudmetrics_raw, monkeypatch):
    monkeypatch.delenv("CLOUDMETRICS_DB_PATH")
    assert "CLOUDMETRICS_DB_PATH is not set" in errors_for(cloudmetrics_raw)


def test_unset_env_var_via_load_config(monkeypatch):
    monkeypatch.delenv("CLOUDMETRICS_DB_PATH")
    with pytest.raises(ConfigError, match="CLOUDMETRICS_DB_PATH is not set"):
        load_config(CLOUDMETRICS_CONFIG)


def test_missing_source_db(cloudmetrics_raw, tmp_path):
    cloudmetrics_raw["path"] = str(tmp_path / "nope.db")
    assert "does not exist" in errors_for(cloudmetrics_raw)


# --- tables and columns against the source DB --------------------------------------


def test_missing_column(cloudmetrics_raw):
    table(cloudmetrics_raw, "customers")["columns"].append({"name": "vip_flag", "type": "INTEGER"})
    assert "tables.customers.vip_flag: column does not exist" in errors_for(cloudmetrics_raw)


def test_missing_table(cloudmetrics_raw):
    table(cloudmetrics_raw, "plans")["name"] = "plan_catalog"
    cloudmetrics_raw["access"]["row_scope"]["reference_tables"] = ["plan_catalog"]
    column(cloudmetrics_raw, "subscriptions", "plan_id")["references"] = "plan_catalog.plan_id"
    assert "tables.plan_catalog: table does not exist" in errors_for(cloudmetrics_raw)


def test_references_unknown_column(cloudmetrics_raw):
    column(cloudmetrics_raw, "subscriptions", "plan_id")["references"] = "plans.id"
    assert "references unknown column plans.id" in errors_for(cloudmetrics_raw)


def test_two_display_names(cloudmetrics_raw):
    column(cloudmetrics_raw, "customers", "account_owner")["display_name"] = True
    assert "more than one display_name" in errors_for(cloudmetrics_raw)


def test_display_name_needs_primary_key(cloudmetrics_raw):
    column(cloudmetrics_raw, "plans", "plan_id")["primary_key"] = False
    column(cloudmetrics_raw, "plans", "plan_name")["display_name"] = True
    msg = errors_for(cloudmetrics_raw)
    assert "display_name requires the table to have a primary_key" in msg


# --- access ------------------------------------------------------------------------


def test_undeclared_sensitive_category(cloudmetrics_raw):
    column(cloudmetrics_raw, "customers", "account_owner")["sensitive"] = "staff"
    assert "sensitive category 'staff' is not declared" in errors_for(cloudmetrics_raw)


def test_sensitive_without_access_section(synthetic_raw):
    del synthetic_raw["access"]
    assert "sensitive category 'contact' is not declared" in errors_for(synthetic_raw)


def test_table_not_covered_by_access(cloudmetrics_raw):
    cloudmetrics_raw["access"]["row_scope"]["reference_tables"] = []
    assert "table 'plans' is not in row_scope.table" in errors_for(cloudmetrics_raw)


def test_table_in_two_access_lists(cloudmetrics_raw):
    cloudmetrics_raw["access"]["row_scope"]["reference_tables"].append("invoices")
    assert "'invoices' appears more than once" in errors_for(cloudmetrics_raw)


def test_row_scope_column_not_listed(cloudmetrics_raw):
    cloudmetrics_raw["access"]["row_scope"]["column"] = "region"
    assert "customers.region is not a listed column" in errors_for(cloudmetrics_raw)


def test_all_is_a_reserved_group_name(cloudmetrics_raw):
    cloudmetrics_raw["access"]["row_scope"]["groups"]["All"] = ["Brazil"]
    assert "'All' is reserved" in errors_for(cloudmetrics_raw)


def test_bad_via_without_references(cloudmetrics_raw):
    cloudmetrics_raw["access"]["row_scope"]["scoped_tables"][1]["via"] = "payment_method"
    msg = errors_for(cloudmetrics_raw)
    assert "via column 'payment_method' declares no `references`" in msg


def test_bad_via_to_reference_table(cloudmetrics_raw):
    cloudmetrics_raw["access"]["row_scope"]["scoped_tables"][0]["via"] = "plan_id"
    msg = errors_for(cloudmetrics_raw)
    assert "references plans, which is neither row_scope.table nor a scoped table" in msg


def test_bad_via_to_non_primary_key(synthetic_raw):
    column(synthetic_raw, "orders", "account_id")["references"] = "accounts.territory"
    msg = errors_for(synthetic_raw)
    assert "via account_id must reference the primary key of accounts" in msg


def test_bad_via_unlisted_column(synthetic_raw):
    synthetic_raw["access"]["row_scope"]["scoped_tables"][1]["via"] = "order_ref"
    assert "via column 'order_ref' is not a listed column" in errors_for(synthetic_raw)


def test_cycle_in_scoped_chain(synthetic_raw):
    # orders -> order_items -> orders: the chain never reaches the row-scope table.
    column(synthetic_raw, "orders", "account_id")["references"] = "order_items.item_id"
    msg = errors_for(synthetic_raw)
    assert "cycle order_items -> orders -> order_items" in msg
    assert msg.count("cycle") == 1


# --- metrics -----------------------------------------------------------------------


def test_broken_metric_sql(cloudmetrics_raw):
    m = metric(cloudmetrics_raw, "revenue")
    m["sql"] = m["sql"].replace("i.amount", "i.amount_usd")
    assert "metrics.revenue.sql: fails on the source database" in errors_for(cloudmetrics_raw)


def test_broken_metric_filter_expression(cloudmetrics_raw):
    metric(cloudmetrics_raw, "revenue")["filters"]["region"] = "c.region"
    assert "metrics.revenue.sql: fails on the source database" in errors_for(cloudmetrics_raw)


def test_broken_breakdown_sql(cloudmetrics_raw):
    m = metric(cloudmetrics_raw, "avg_resolution_hours")
    m["breakdown_sql"] = m["breakdown_sql"].replace("t.priority AS label", "t.urgency AS label")
    assert "avg_resolution_hours.breakdown_sql: fails" in errors_for(cloudmetrics_raw)


def test_metric_without_value_column(cloudmetrics_raw):
    m = metric(cloudmetrics_raw, "new_customers")
    m["sql"] = m["sql"].replace("AS value", "AS n")
    msg = errors_for(cloudmetrics_raw)
    assert "new_customers.sql: result has no column(s) named value" in msg


def test_metric_must_be_select(cloudmetrics_raw):
    metric(cloudmetrics_raw, "customer_count")["sql"] = "DELETE FROM customers WHERE 1 {{filters}}"
    assert "customer_count.sql: must be a single SELECT" in errors_for(cloudmetrics_raw)


def test_metric_multiple_statements(cloudmetrics_raw):
    m = metric(cloudmetrics_raw, "customer_count")
    m["sql"] = m["sql"] + "; SELECT 1"
    assert "customer_count.sql: fails on the source database" in errors_for(cloudmetrics_raw)


def test_period_metric_must_use_start_and_end(cloudmetrics_raw):
    m = metric(cloudmetrics_raw, "new_customers")
    m["sql"] = m["sql"].replace("AND c.signup_date < :end", "")
    assert "period metric sql must use :end" in errors_for(cloudmetrics_raw)


def test_period_time_column_must_be_a_date(cloudmetrics_raw):
    metric(cloudmetrics_raw, "revenue")["time_column"] = "invoices.amount"
    assert "time_column invoices.amount is not DATE or DATETIME" in errors_for(cloudmetrics_raw)


def test_snapshot_metric_with_trend(cloudmetrics_raw):
    metric(cloudmetrics_raw, "mrr")["trend"] = {"grain": "month", "periods": 12}
    assert "metrics.mrr: trend is for period metrics only" in errors_for(cloudmetrics_raw)


def test_duplicate_metric_name(cloudmetrics_raw):
    metric(cloudmetrics_raw, "arpu")["name"] = "mrr"
    assert "duplicate name 'mrr'" in errors_for(cloudmetrics_raw)


def test_bad_unit(cloudmetrics_raw):
    metric(cloudmetrics_raw, "mrr")["unit"] = "dollars"
    assert "unit" in errors_for(cloudmetrics_raw)


def test_errors_are_collected_together(cloudmetrics_raw):
    column(cloudmetrics_raw, "customers", "account_owner")["sensitive"] = "staff"
    cloudmetrics_raw["access"]["row_scope"]["reference_tables"] = []
    with pytest.raises(ConfigError) as exc:
        validate_config(parse_config(cloudmetrics_raw))
    assert len(exc.value.errors) == 2
