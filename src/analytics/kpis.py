"""Inventory cost and business KPIs.

Definitions
-----------
* Inventory value = on-hand quantity x unit cost.
* Average inventory value: only one stock snapshot per SKU is available, so the
  current inventory value is used as the estimate of average inventory.
* Estimated annual holding cost = average inventory value x annual holding-cost rate.
* COGS (period) = units sold in the analysis window x unit cost.
* Inventory turnover (period) = COGS (period) / average inventory value.
  Annualised turnover = period turnover x 365 / window days.
* Days of inventory on hand = window days / period turnover.
* Excess inventory value = excess units x unit cost (see planning.py).
* Potential stock-out exposure = potential shortfall over one lead time x selling
  price. This is revenue at risk *if nothing is done*, an estimate only.
All ratios return None when the denominator is zero, so no misleading numbers.
"""
import pandas as pd

from src.inventory.planning import STATUS_INSUFFICIENT, STATUS_REORDER


def _ratio(num: float, den: float) -> float | None:
    return float(num) / float(den) if den and den > 0 else None


def inventory_kpis(plan: pd.DataFrame, window, holding_cost_rate: float) -> dict:
    inventory_value = float(plan["inventory_value"].sum())
    cogs = float((plan["total_qty"].fillna(0) * plan["unit_cost"]).sum())
    window_days = window.days if window else None
    turnover = _ratio(cogs, inventory_value) if window else None
    meaningful = plan["alert_status"] != STATUS_INSUFFICIENT
    return {
        "sku_count": int(len(plan)),
        "inventory_value": inventory_value,
        "on_hand_units": float(plan["on_hand_qty"].sum()),
        "holding_cost": inventory_value * holding_cost_rate,
        "cogs_period": cogs,
        "window_days": window_days,
        "turnover_period": turnover,
        "turnover_annualised": turnover * window.annualisation_factor if turnover else None,
        "days_inventory_on_hand": _ratio(window_days, turnover) if turnover else None,
        "reorder_required": int((plan["alert_status"] == STATUS_REORDER).sum()),
        "below_safety_stock": int(plan["below_safety_stock"].sum()),
        "excess_value": float(plan["excess_value"].sum()),
        "excess_skus": int((plan["excess_qty"] > 0).sum()),
        "stockout_exposure": float(plan["stockout_exposure_value"].sum()),
        "suggested_spend": float(plan["estimated_order_cost"].sum()),
        "insufficient_data": int((~meaningful).sum()),
        "out_of_stock": int(((plan["available_qty"] <= 0) & (plan["planning_daily_demand"] > 0)).sum()),
    }


def summary_by(plan: pd.DataFrame, by: str | list[str]) -> pd.DataFrame:
    """Inventory, excess and alert summary by any grouping column(s)."""
    out = (plan.groupby(by)
           .agg(products=("sku_id", "count"), on_hand_units=("on_hand_qty", "sum"),
                inventory_value=("inventory_value", "sum"),
                excess_value=("excess_value", "sum"),
                reorder_required=("alert_status", lambda s: int((s == STATUS_REORDER).sum())),
                suggested_order_cost=("estimated_order_cost", "sum"))
           .reset_index())
    total = out["inventory_value"].sum()
    out["share_of_inventory_value"] = out["inventory_value"] / total if total > 0 else 0.0
    return out.sort_values("inventory_value", ascending=False)
