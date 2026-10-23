"""Stock position, incoming orders, alerts, replenishment, scenarios and KPIs on a tiny dataset."""
import math

import pytest

from src.analytics.pipeline import run_analysis
from src.config import AnalysisSettings
from src.inventory import planning as p
from src.inventory.scenarios import compare_scenarios, scenario_plans
from tests.helpers import build, daily_sales

PRODUCTS = """sku_id,product_name,category,unit_cost,selling_price,on_hand_qty,reserved_qty,min_order_qty,order_multiple,supplier_id,snapshot_date
REORDER,Needs order,Cat,2,4,40,0,100,50,S1,2026-01-30
EXCESS,Too much,Cat,2,4,1000,0,,,S1,2026-01-30
NODEMAND,Dead stock,Cat,5,8,20,0,,,S1,2026-01-30
NOSUP,Unknown supplier,Cat,2,4,10,0,,,S9,2026-01-30
LOW,Low but incoming,Cat,2,4,0,0,,,S1,2026-01-30
RESERVED,Reserved stock,Cat,2,4,100,60,,,S1,2026-01-30"""
SUPPLIERS = "supplier_id,supplier_name,avg_lead_time_days,lead_time_std_days\nS1,Supplier,5,0"
POS = """po_id,sku_id,order_qty,order_date,expected_delivery_date,actual_delivery_date,status
P1,REORDER,5,2026-01-28,2026-02-02,,open
P2,REORDER,1000,2026-01-28,2026-02-02,,cancelled
P3,REORDER,1000,2026-01-01,2026-01-06,2026-01-06,received
P4,LOW,400,2026-01-28,2026-02-02,,in_transit
P5,REORDER,999,2026-01-20,2026-01-25,2026-01-25,open"""
SALES = "\n".join(daily_sales(s, [10] * 30) for s in ("REORDER", "EXCESS", "NOSUP", "LOW", "RESERVED"))


@pytest.fixture(scope="module")
def result():
    dataset, validation = build(PRODUCTS, SALES, SUPPLIERS, POS)
    assert dataset is not None, validation.blocking_errors
    return run_analysis(dataset, AnalysisSettings())


def row(result, sku):
    return result.plan.set_index("sku_id").loc[sku]


def test_only_open_and_in_transit_orders_count_as_incoming(result):
    r = row(result, "REORDER")
    assert r["open_po_qty"] == 5            # cancelled, received and delivered "open" ignored
    assert r["stock_position"] == 45        # 40 - 0 + 5
    assert row(result, "LOW")["in_transit_qty"] == 400


def test_reserved_stock_reduces_stock_position(result):
    r = row(result, "RESERVED")
    assert r["available_qty"] == 40 and r["stock_position"] == 40


def test_constant_demand_zero_variability(result):
    r = row(result, "REORDER")
    assert r["avg_daily_demand"] == 10 and r["std_daily_demand"] == 0
    assert r["safety_stock"] == 0
    assert r["reorder_point"] == 50          # 10/day x 5 days


def test_reorder_quantity_respects_moq_and_multiple(result):
    r = row(result, "REORDER")
    assert r["alert_status"] == p.STATUS_REORDER
    # target = 50 + 30 x 10 = 350; raw = 350 - 45 = 305 -> multiple of 50 = 350
    assert r["target_stock_level"] == 350
    assert r["suggested_order_qty"] == 350
    assert r["estimated_order_cost"] == 700


def test_excess_inventory(result):
    r = row(result, "EXCESS")
    assert r["alert_status"] == p.STATUS_EXCESS
    assert r["excess_qty"] == 50             # 1000 - (350 + 60 x 10)
    assert r["suggested_order_qty"] == 0


def test_no_demand_product(result):
    r = row(result, "NODEMAND")
    assert r["xyz_class"] == "No Demand"
    assert r["alert_status"] == p.STATUS_EXCESS
    assert r["excess_qty"] == 20 and r["stockout_risk"] == p.RISK_NONE


def test_unknown_supplier_is_insufficient_data(result):
    r = row(result, "NOSUP")
    assert r["alert_status"] == p.STATUS_INSUFFICIENT
    assert math.isnan(r["reorder_point"]) and math.isnan(r["suggested_order_qty"])


def test_low_stock_with_incoming_order(result):
    r = row(result, "LOW")
    assert r["alert_status"] == p.STATUS_LOW
    assert r["stockout_risk"] == p.RISK_OUT


def test_insufficient_history():
    dataset, _ = build(PRODUCTS, daily_sales("REORDER", [10] * 10), SUPPLIERS)
    result = run_analysis(dataset, AnalysisSettings(min_history_days=28))
    assert set(result.plan["alert_status"]) == {p.STATUS_INSUFFICIENT}


def test_without_purchase_orders_incoming_is_zero():
    dataset, _ = build(PRODUCTS, SALES, SUPPLIERS)
    result = run_analysis(dataset, AnalysisSettings())
    assert row(result, "REORDER")["stock_position"] == 40
    assert any("No purchase-order file" in n for n in dataset.notes)


def test_service_level_change_recalculates_safety_stock():
    sales = daily_sales("REORDER", [5, 15] * 15)
    dataset, _ = build(PRODUCTS, sales, SUPPLIERS)
    low = run_analysis(dataset, AnalysisSettings(service_level=0.90))
    high = run_analysis(dataset, AnalysisSettings(service_level=0.99))
    ss_low, ss_high = row(low, "REORDER")["safety_stock"], row(high, "REORDER")["safety_stock"]
    assert ss_high / ss_low == pytest.approx(2.326 / 1.282)
    assert row(high, "REORDER")["reorder_point"] > row(low, "REORDER")["reorder_point"]


def test_lead_time_std_from_purchase_order_history():
    suppliers = "supplier_id,supplier_name,avg_lead_time_days\nS1,Supplier,5"
    pos = """po_id,sku_id,order_qty,order_date,expected_delivery_date,actual_delivery_date,status
        P1,REORDER,10,2026-01-01,2026-01-06,2026-01-05,received
        P2,REORDER,10,2026-01-01,2026-01-06,2026-01-06,received
        P3,REORDER,10,2026-01-01,2026-01-06,2026-01-07,received"""
    dataset, _ = build(PRODUCTS, SALES, suppliers, pos)
    r = row(run_analysis(dataset, AnalysisSettings()), "REORDER")
    assert r["lead_time_source"] == "Purchase-order history"
    assert r["lead_time_std_applied"] == pytest.approx(1.0)     # sample std of 4, 5, 6 days
    assert r["ss_model"] == p.MODEL_COMBINED
    # SS = 1.645 x sqrt(5 x 0 + 10^2 x 1) = 16.45
    assert r["safety_stock"] == pytest.approx(16.45)


def test_fixed_lead_time_model_when_no_variability_data():
    suppliers = "supplier_id,supplier_name,avg_lead_time_days\nS1,Supplier,5"
    dataset, _ = build(PRODUCTS, SALES, suppliers)
    r = row(run_analysis(dataset, AnalysisSettings()), "REORDER")
    assert r["ss_model"] == p.MODEL_FIXED


def test_scenarios_use_same_inputs_and_increase_with_service_level():
    sales = "\n".join(daily_sales(s, [5, 15] * 15) for s in ("REORDER", "EXCESS"))
    dataset, _ = build(PRODUCTS, sales, SUPPLIERS)
    base = run_analysis(dataset, AnalysisSettings())
    prep = base.prepared
    plans = scenario_plans(prep.classified, prep.lead_times, prep.incoming, AnalysisSettings(),
                           (0.90, 0.95, 0.99))
    table = compare_scenarios(plans, AnalysisSettings())
    assert table["safety_stock_value"].is_monotonic_increasing
    assert table["additional_safety_stock_investment"].iloc[0] == 0
    assert table.loc[1, "safety_stock_value"] == pytest.approx(
        (base.plan["safety_stock"] * base.plan["unit_cost"]).sum())


def test_kpis(result):
    k = result.kpis
    # 40x2 + 1000x2 + 20x5 + 10x2 + 0 + 100x2
    assert k["inventory_value"] == 2400
    assert k["holding_cost"] == pytest.approx(600)            # 25%
    assert k["cogs_period"] == 5 * 300 * 2                     # 5 SKUs x 300 units x $2
    assert k["turnover_period"] == pytest.approx(3000 / 2400)
    assert k["days_inventory_on_hand"] == pytest.approx(30 / (3000 / 2400))
    assert k["reorder_required"] == int((result.plan["alert_status"] == p.STATUS_REORDER).sum())
