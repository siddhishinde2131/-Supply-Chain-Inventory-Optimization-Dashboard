"""Inputs for stock position and safety stock: incoming orders and lead times.

Incoming stock rule
-------------------
Only purchase orders with status ``open`` or ``in_transit`` AND no actual delivery
date count as incoming. Received and cancelled orders never count (received
stock is already part of on-hand).

Lead-time variability rule (per supplier)
-----------------------------------------
1. ``lead_time_std_days`` from the suppliers file, if provided.
2. Otherwise the sample standard deviation of observed lead times
   (actual delivery - order date) from received purchase orders, if at least
   ``min_observations`` exist.
3. Otherwise no variability data -> the fixed-lead-time safety-stock model is used.
The *average* lead time always comes from the suppliers file (the agreed value).
"""
import numpy as np
import pandas as pd

from src.data.schema import INCOMING_PO_STATUSES

LT_FROM_SUPPLIER = "Supplier file"
LT_FROM_PO = "Purchase-order history"
LT_NONE = "Not available"


def incoming_quantities(purchase_orders: pd.DataFrame | None) -> pd.DataFrame:
    """Open and in-transit quantities per SKU (eligible orders only)."""
    cols = ["open_po_qty", "in_transit_qty", "open_po_count"]
    if purchase_orders is None or purchase_orders.empty:
        return pd.DataFrame(columns=cols, index=pd.Index([], name="sku_id"), dtype=float)
    po = purchase_orders
    eligible = po[po["status"].isin(INCOMING_PO_STATUSES) & po["actual_delivery_date"].isna()]
    out = pd.DataFrame({
        "open_po_qty": eligible[eligible["status"] == "open"].groupby("sku_id")["order_qty"].sum(),
        "in_transit_qty": eligible[eligible["status"] == "in_transit"].groupby("sku_id")["order_qty"].sum(),
        "open_po_count": eligible.groupby("sku_id").size(),
    }).fillna(0.0)
    out.index.name = "sku_id"
    return out


def observed_lead_times(purchase_orders: pd.DataFrame | None) -> pd.DataFrame:
    """One row per received order with its observed lead time in days."""
    if purchase_orders is None or purchase_orders.empty:
        return pd.DataFrame(columns=["po_id", "sku_id", "observed_lead_time_days",
                                     "delay_days", "on_time"])
    po = purchase_orders
    received = po[(po["status"] == "received") & po["actual_delivery_date"].notna()].copy()
    received["observed_lead_time_days"] = (received["actual_delivery_date"]
                                           - received["order_date"]).dt.days
    received["delay_days"] = (received["actual_delivery_date"]
                              - received["expected_delivery_date"]).dt.days
    received["on_time"] = received["delay_days"] <= 0
    return received


def supplier_lead_time_parameters(suppliers: pd.DataFrame, products: pd.DataFrame,
                                  purchase_orders: pd.DataFrame | None,
                                  min_observations: int = 3) -> pd.DataFrame:
    """Average lead time, lead-time std and its source for each supplier."""
    sup = suppliers.set_index("supplier_id")[["supplier_name", "avg_lead_time_days",
                                              "lead_time_std_days"]].copy()
    obs = observed_lead_times(purchase_orders)
    if not obs.empty:
        obs = obs.merge(products[["sku_id", "supplier_id"]], on="sku_id", how="left")
        po_stats = obs.groupby("supplier_id")["observed_lead_time_days"].agg(["count", "std"])
    else:
        po_stats = pd.DataFrame(columns=["count", "std"], dtype=float)
    sup = sup.join(po_stats.rename(columns={"count": "lt_observations", "std": "observed_lt_std"}))
    sup["lt_observations"] = sup["lt_observations"].fillna(0).astype(int)

    from_supplier = sup["lead_time_std_days"].notna()
    from_po = ~from_supplier & (sup["lt_observations"] >= min_observations) \
        & sup["observed_lt_std"].notna()
    sup["lead_time_source"] = np.select([from_supplier, from_po], [LT_FROM_SUPPLIER, LT_FROM_PO],
                                        default=LT_NONE)
    sup["lead_time_std_used"] = np.select(
        [from_supplier, from_po], [sup["lead_time_std_days"], sup["observed_lt_std"]],
        default=np.nan)
    return sup.reset_index()
