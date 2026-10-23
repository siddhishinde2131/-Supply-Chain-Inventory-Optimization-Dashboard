"""Supplier lead-time analysis: stated vs observed lead times and reliability."""
import numpy as np
import pandas as pd

from src.inventory.stock import observed_lead_times

# Review rules (documented on the Business Insights page)
LATE_FACTOR = 1.20        # observed average lead time > 120% of the stated average
MIN_ON_TIME_RATE = 0.80   # fewer than 80% of orders on time
MAX_LT_CV = 0.50          # lead-time std / mean above 0.5 = unreliable


def supplier_lead_time_analysis(suppliers: pd.DataFrame, products: pd.DataFrame,
                                purchase_orders: pd.DataFrame | None,
                                lead_times: pd.DataFrame) -> pd.DataFrame:
    obs = observed_lead_times(purchase_orders)
    base = lead_times.set_index("supplier_id")[
        ["supplier_name", "avg_lead_time_days", "lead_time_std_days", "lead_time_source",
         "lead_time_std_used"]]
    base["skus_supplied"] = products.groupby("supplier_id").size().reindex(base.index).fillna(0).astype(int)
    if not obs.empty:
        obs = obs.merge(products[["sku_id", "supplier_id"]], on="sku_id", how="left")
        agg = obs.groupby("supplier_id").agg(
            received_orders=("po_id", "count"),
            observed_avg_lead_time=("observed_lead_time_days", "mean"),
            observed_lead_time_std=("observed_lead_time_days", "std"),
            on_time_rate=("on_time", "mean"),
            avg_delay_days=("delay_days", "mean"))
        base = base.join(agg)
    else:
        for col in ("received_orders", "observed_avg_lead_time", "observed_lead_time_std",
                    "on_time_rate", "avg_delay_days"):
            base[col] = np.nan
    base["received_orders"] = base["received_orders"].fillna(0).astype(int)
    reasons = []
    for _, r in base.iterrows():
        why = []
        if r["received_orders"] > 0:
            if r["observed_avg_lead_time"] > LATE_FACTOR * r["avg_lead_time_days"]:
                why.append(f"actual lead time {r['observed_avg_lead_time']:.1f}d vs stated "
                           f"{r['avg_lead_time_days']:.0f}d")
            if r["on_time_rate"] < MIN_ON_TIME_RATE:
                why.append(f"on-time rate {r['on_time_rate']:.0%}")
        lt_std = r["lead_time_std_used"]
        if pd.notna(lt_std) and r["avg_lead_time_days"] > 0 \
                and lt_std / r["avg_lead_time_days"] > MAX_LT_CV:
            why.append("highly variable lead time")
        if pd.isna(lt_std):
            why.append("no lead-time variability data")
        reasons.append("; ".join(why))
    base["review_reason"] = reasons
    base["needs_review"] = base["review_reason"] != ""
    return base.reset_index().sort_values(["needs_review", "skus_supplied"], ascending=False)
