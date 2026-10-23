"""Per-SKU inventory plan: safety stock, reorder point, alerts and suggested orders.

Replenishment policy (transparent, reviewable)
-----------------------------------------------
* Trigger: stock position <= reorder point.
* Quantity: order up to the target level = ROP + ``target_coverage_days`` of demand,
  i.e. raw quantity = target level - stock position.
* The raw quantity is raised to the minimum order quantity and rounded UP to the
  order multiple when those are provided.
* These are recommendations for a planner to review; no order is created.

Alert statuses (checked in this order)
--------------------------------------
1. Insufficient Data  - no lead time (unknown supplier) or too little history.
2. Reorder Required   - stock position <= reorder point.
3. Low Stock          - stock position is above ROP only thanks to incoming orders,
                        but available stock is at or below safety stock.
4. Excess Inventory Review - available stock above target level + excess buffer days,
                        or stock held with no demand in the period.
5. No Recent Demand   - no demand and no stock.
6. Above Reorder Point - none of the above.
Stock-out flags describe a *potential* risk under the model assumptions, not a
certainty.
"""
import numpy as np
import pandas as pd

from src.analytics.classification import INSUFFICIENT
from src.config import AnalysisSettings
from src.inventory import formulas as f

STATUS_REORDER = "Reorder Required"
STATUS_LOW = "Low Stock"
STATUS_OK = "Above Reorder Point"
STATUS_EXCESS = "Excess Inventory Review"
STATUS_INSUFFICIENT = "Insufficient Data"
STATUS_NO_DEMAND = "No Recent Demand"
ALERT_STATUSES = (STATUS_REORDER, STATUS_LOW, STATUS_OK, STATUS_EXCESS,
                  STATUS_NO_DEMAND, STATUS_INSUFFICIENT)

RISK_OUT = "Out of stock now"
RISK_HIGH = "High"
RISK_ELEVATED = "Elevated"
RISK_LOW = "Low"
RISK_NONE = "No demand"
RISK_UNKNOWN = "Unknown"
RISK_LEVELS = (RISK_OUT, RISK_HIGH, RISK_ELEVATED, RISK_LOW, RISK_NONE, RISK_UNKNOWN)

MODEL_COMBINED = "Demand + lead-time variability"
MODEL_FIXED = "Fixed lead time (demand variability only)"


def build_inventory_plan(classified: pd.DataFrame, lead_times: pd.DataFrame,
                         incoming: pd.DataFrame, settings: AnalysisSettings,
                         service_level: float | None = None, demand_factor: float = 1.0,
                         lead_time_factor: float = 1.0) -> pd.DataFrame:
    """Calculate the full plan for every product.

    ``demand_factor`` and ``lead_time_factor`` scale demand / lead time for what-if
    scenarios (1.0 = as observed).
    """
    service_level = settings.service_level if service_level is None else service_level
    z = f.z_score(service_level)
    df = classified.merge(
        lead_times[["supplier_id", "supplier_name", "avg_lead_time_days",
                    "lead_time_std_used", "lead_time_source"]],
        on="supplier_id", how="left")
    df = df.join(incoming, on="sku_id")
    for col in ("open_po_qty", "in_transit_qty", "open_po_count"):
        df[col] = df[col].fillna(0.0) if col in df else 0.0
    df["lead_time_source"] = df["lead_time_source"].fillna("Supplier not found")

    # --- stock position -------------------------------------------------------
    df["available_qty"] = df["on_hand_qty"] - df["reserved_qty"]
    df["incoming_qty"] = df["open_po_qty"] + df["in_transit_qty"]
    df["stock_position"] = f.stock_position(df["on_hand_qty"], df["reserved_qty"],
                                            df["incoming_qty"])
    df["inventory_value"] = df["on_hand_qty"] * df["unit_cost"]

    # --- demand & lead time inputs -------------------------------------------
    d = df["avg_daily_demand"].fillna(0) * demand_factor
    var_d = df["demand_variance"].fillna(0) * demand_factor ** 2
    lead = df["avg_lead_time_days"] * lead_time_factor
    lt_std = pd.to_numeric(df["lead_time_std_used"], errors="coerce") * lead_time_factor
    combined = settings.use_lead_time_variability & lt_std.notna()
    var_l = np.where(combined, lt_std.fillna(0) ** 2, 0.0)
    df["ss_model"] = np.where(combined, MODEL_COMBINED, MODEL_FIXED)

    insufficient = lead.isna() | (df["xyz_class"] == INSUFFICIENT) | df["avg_daily_demand"].isna()
    lead_filled = lead.fillna(0)

    df["service_level"] = service_level
    df["z_score"] = z
    df["planning_daily_demand"] = d
    df["planning_lead_time_days"] = lead
    df["lead_time_std_applied"] = np.where(combined, lt_std, 0.0)
    df["safety_stock"] = f.safety_stock(z, d, var_d, lead_filled, var_l)
    df["lead_time_demand"] = f.lead_time_demand(d, lead_filled)
    df["reorder_point"] = f.reorder_point(d, lead_filled, df["safety_stock"])
    df["target_stock_level"] = f.target_stock_level(df["reorder_point"], d,
                                                    settings.target_coverage_days)
    df["suggested_order_qty"] = f.replenishment_quantity(
        df["stock_position"], df["reorder_point"], df["target_stock_level"],
        df["min_order_qty"], df["order_multiple"])
    excess_threshold = df["target_stock_level"] + d * settings.excess_buffer_days
    df["excess_qty"] = np.clip(df["available_qty"] - excess_threshold, 0, None)
    df["days_of_cover"] = f.safe_divide(df["available_qty"].clip(lower=0), d)
    df["below_safety_stock"] = (d > 0) & (df["available_qty"] < df["safety_stock"])

    # Values that cannot be calculated reliably are blanked, not guessed.
    for col in ("safety_stock", "lead_time_demand", "reorder_point", "target_stock_level",
                "suggested_order_qty", "excess_qty"):
        df.loc[insufficient, col] = np.nan
    df.loc[insufficient, "below_safety_stock"] = False
    df["estimated_order_cost"] = df["suggested_order_qty"] * df["unit_cost"]
    df["excess_value"] = df["excess_qty"] * df["unit_cost"]

    # --- alert status ---------------------------------------------------------
    no_demand = ~insufficient & (d <= 0)
    reorder = ~insufficient & ~no_demand & (df["stock_position"] <= df["reorder_point"])
    low = ~insufficient & ~no_demand & ~reorder & (df["available_qty"] <= df["safety_stock"])
    excess = ~insufficient & ~reorder & ~low & (df["excess_qty"] > 0)
    df["alert_status"] = np.select(
        [insufficient, reorder, low, excess, no_demand],
        [STATUS_INSUFFICIENT, STATUS_REORDER, STATUS_LOW, STATUS_EXCESS, STATUS_NO_DEMAND],
        default=STATUS_OK)
    df["status_reason"] = np.select(
        [insufficient & lead.isna(), insufficient, reorder, low, excess & no_demand, excess,
         no_demand],
        ["Supplier lead time unknown (supplier missing from suppliers file).",
         f"Less than {settings.min_history_days} days of sales history.",
         "Stock position is at or below the reorder point.",
         "Available stock is at or below safety stock; incoming orders keep the stock "
         "position above the reorder point - check delivery dates.",
         "Stock is held but no demand was recorded in the analysis period.",
         f"Available stock exceeds target level + {settings.excess_buffer_days} days of demand.",
         "No demand and no stock."],
        default="Stock position is above the reorder point.")

    # --- potential stock-out risk --------------------------------------------
    out_now = ~insufficient & (d > 0) & (df["available_qty"] <= 0)
    high = ~insufficient & (d > 0) & (df["stock_position"] < df["lead_time_demand"])
    elevated = ~insufficient & (d > 0) & reorder
    df["stockout_risk"] = np.select(
        [insufficient, no_demand, out_now, high, elevated],
        [RISK_UNKNOWN, RISK_NONE, RISK_OUT, RISK_HIGH, RISK_ELEVATED], default=RISK_LOW)
    shortfall = np.clip(df["lead_time_demand"] - df["stock_position"], 0, None)
    df["potential_shortfall_units"] = np.where(insufficient, np.nan, shortfall)
    df["stockout_exposure_value"] = df["potential_shortfall_units"] * df["selling_price"]
    return df


PLAN_DISPLAY_COLUMNS = [
    "sku_id", "product_name", "category", "supplier_id", "supplier_name", "abc_class",
    "xyz_class", "abc_xyz", "on_hand_qty", "reserved_qty", "available_qty", "open_po_qty",
    "in_transit_qty", "stock_position", "avg_daily_demand", "std_daily_demand",
    "avg_lead_time_days", "lead_time_std_applied", "lead_time_source", "ss_model",
    "service_level", "z_score", "safety_stock", "reorder_point", "target_stock_level",
    "suggested_order_qty", "min_order_qty", "order_multiple", "unit_cost",
    "estimated_order_cost", "days_of_cover", "alert_status", "status_reason",
    "stockout_risk", "potential_shortfall_units", "stockout_exposure_value",
]


def lead_time_model_counts(plan: pd.DataFrame) -> pd.DataFrame:
    """How many SKUs use each safety-stock model / lead-time source."""
    return (plan.groupby(["ss_model", "lead_time_source"]).size()
            .rename("products").reset_index())
