"""Service-level scenario comparison.

Every scenario uses the same products, demand statistics, lead times and stock
data; only the service level (and optional what-if factors) change, so the
comparison is fair.

Estimated average inventory under the policy
---------------------------------------------
Average inventory ~= safety stock + half of a typical replenishment quantity.
With the order-up-to policy a typical order covers ``target_coverage_days`` of
demand, so cycle stock ~= demand x coverage days / 2. This is a planning estimate,
not a forecast of actual stock levels.
"""
import pandas as pd

from src.config import AnalysisSettings
from src.inventory.planning import STATUS_INSUFFICIENT, STATUS_REORDER, build_inventory_plan


def scenario_plans(classified, lead_times, incoming, settings: AnalysisSettings,
                   service_levels, demand_factor=1.0, lead_time_factor=1.0) -> dict:
    """Plan per service level (same inputs for each)."""
    return {sl: build_inventory_plan(classified, lead_times, incoming, settings, sl,
                                     demand_factor, lead_time_factor)
            for sl in service_levels}


def compare_scenarios(plans: dict, settings: AnalysisSettings,
                      holding_cost_rate: float | None = None) -> pd.DataFrame:
    """Summary table: one row per service level."""
    rate = settings.holding_cost_rate if holding_cost_rate is None else holding_cost_rate
    rows = []
    for sl, plan in sorted(plans.items()):
        valid = plan[plan["alert_status"] != STATUS_INSUFFICIENT]
        ss_value = (valid["safety_stock"] * valid["unit_cost"]).sum()
        cycle_value = (valid["planning_daily_demand"] * settings.target_coverage_days / 2
                       * valid["unit_cost"]).sum()
        avg_inventory_value = ss_value + cycle_value
        rows.append({
            "service_level": sl,
            "z_score": plan["z_score"].iloc[0] if len(plan) else None,
            "safety_stock_units": valid["safety_stock"].sum(),
            "safety_stock_value": ss_value,
            "reorder_required": int((plan["alert_status"] == STATUS_REORDER).sum()),
            "suggested_order_units": valid["suggested_order_qty"].sum(),
            "suggested_order_cost": valid["estimated_order_cost"].sum(),
            "estimated_avg_inventory_value": avg_inventory_value,
            "estimated_annual_holding_cost": avg_inventory_value * rate,
            "safety_stock_holding_cost": ss_value * rate,
        })
    out = pd.DataFrame(rows)
    if not out.empty:
        base = out.iloc[0]
        out["additional_safety_stock_investment"] = out["safety_stock_value"] - base["safety_stock_value"]
        out["additional_annual_holding_cost"] = (out["estimated_annual_holding_cost"]
                                                 - base["estimated_annual_holding_cost"])
    return out


def sku_scenario_table(plans: dict) -> pd.DataFrame:
    """Safety stock and reorder point per SKU, one column pair per service level."""
    frames = []
    for sl, plan in sorted(plans.items()):
        pct = f"{sl:.0%}" if round(sl * 100) == sl * 100 else f"{sl:.1%}"
        frames.append(plan.set_index("sku_id")[["safety_stock", "reorder_point",
                                                "suggested_order_qty"]]
                      .add_suffix(f" @ {pct}"))
    base = next(iter(plans.values())).set_index("sku_id")[
        ["product_name", "category", "abc_class", "xyz_class", "stock_position", "unit_cost"]]
    return base.join(frames).reset_index()
