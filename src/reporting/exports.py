"""CSV report builders. Every report is built from the current dataset/filters."""
import re
from datetime import date

import pandas as pd

from src.analytics.classification import ABC_MEANING
from src.data.quality import missing_values_table, quality_summary
from src.inventory.planning import (PLAN_DISPLAY_COLUMNS, RISK_ELEVATED, RISK_HIGH,
                                    RISK_OUT)


def to_csv_bytes(frame: pd.DataFrame) -> bytes:
    """UTF-8 with BOM so Excel on Windows opens special characters correctly."""
    return frame.to_csv(index=False, float_format="%.4f").encode("utf-8-sig")


def report_filename(report: str, dataset_label: str, suffix: str = "") -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", dataset_label.lower()).strip("_")[:40]
    extra = f"_{suffix}" if suffix else ""
    return f"{report}_{slug}{extra}_{date.today():%Y%m%d}.csv"


def cleaned_inventory_report(plan: pd.DataFrame) -> pd.DataFrame:
    cols = ["sku_id", "product_name", "category", "supplier_id", "unit_cost", "selling_price",
            "on_hand_qty", "reserved_qty", "available_qty", "open_po_qty", "in_transit_qty",
            "stock_position", "inventory_value", "min_order_qty", "order_multiple",
            "snapshot_date", "total_qty", "avg_daily_demand", "std_daily_demand",
            "days_of_cover", "excess_qty", "excess_value"]
    return plan[cols]


def classification_report(plan: pd.DataFrame) -> pd.DataFrame:
    cols = ["sku_id", "product_name", "category", "supplier_id", "unit_cost", "total_qty",
            "annual_demand_estimate", "observed_consumption_value", "annual_consumption_value",
            "value_share", "cumulative_share", "abc_rank", "abc_class", "abc_note",
            "avg_daily_demand", "std_daily_demand", "cv", "history_days", "xyz_class",
            "abc_xyz", "group_focus", "recommendation", "inventory_value"]
    out = plan[cols].sort_values("abc_rank")
    return out.assign(abc_meaning=out["abc_class"].map(ABC_MEANING))


def replenishment_report(plan: pd.DataFrame) -> pd.DataFrame:
    return plan[PLAN_DISPLAY_COLUMNS].sort_values(
        ["alert_status", "estimated_order_cost"], ascending=[True, False])


def stockout_risk_report(plan: pd.DataFrame) -> pd.DataFrame:
    at_risk = plan[plan["stockout_risk"].isin([RISK_OUT, RISK_HIGH, RISK_ELEVATED])]
    cols = ["sku_id", "product_name", "category", "supplier_id", "abc_class", "xyz_class",
            "available_qty", "incoming_qty", "stock_position", "avg_daily_demand",
            "avg_lead_time_days", "lead_time_demand", "safety_stock", "reorder_point",
            "days_of_cover", "stockout_risk", "potential_shortfall_units",
            "stockout_exposure_value", "suggested_order_qty", "estimated_order_cost"]
    return at_risk[cols].sort_values("stockout_exposure_value", ascending=False)


def data_quality_report(validation) -> pd.DataFrame:
    """Summary, missing values, issue counts and individual issues in one CSV."""
    parts = [
        quality_summary(validation).assign(section="1. File summary"),
        missing_values_table(validation).assign(section="2. Missing values"),
        validation.issue_summary().assign(section="3. Issue counts"),
        validation.issues_frame().assign(section="4. Issue details (first 200 per rule)"),
    ]
    frame = pd.concat(parts, ignore_index=True)
    return frame[["section"] + [c for c in frame.columns if c != "section"]]
