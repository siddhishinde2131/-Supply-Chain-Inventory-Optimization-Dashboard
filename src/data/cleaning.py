"""Turn validated files into the clean ``Dataset`` used by every analysis.

Documented cleaning rules
-------------------------
* Rows with validation errors are excluded (they are listed in the quality report).
* ``reserved_qty`` blank -> 0 (no reservations recorded).
* ``min_order_qty`` / ``order_multiple`` blank -> no constraint.
* ``lead_time_std_days`` blank -> estimated from received purchase orders when
  enough observations exist, otherwise the fixed-lead-time model is used.
* Several sales rows for the same SKU and date are summed into one daily total.
* Outliers are only flagged, never removed: a big order is a real business event.
"""
import uuid
from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd


@dataclass
class Dataset:
    products: pd.DataFrame
    sales: pd.DataFrame              # one row per sku_id + sale_date
    suppliers: pd.DataFrame
    purchase_orders: pd.DataFrame | None
    label: str
    source_type: str                 # "sample_csv", "upload_csv" or "postgresql"
    is_synthetic: bool
    validation: object = None        # DatasetValidation
    notes: list[str] = field(default_factory=list)
    dataset_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    loaded_at: datetime = field(default_factory=datetime.now)

    @property
    def has_purchase_orders(self) -> bool:
        return self.purchase_orders is not None and len(self.purchase_orders) > 0

    @property
    def sales_period(self) -> tuple[pd.Timestamp, pd.Timestamp] | None:
        if self.sales.empty:
            return None
        return self.sales["sale_date"].min(), self.sales["sale_date"].max()


def clean_products(products: pd.DataFrame, notes: list[str]) -> pd.DataFrame:
    df = products.copy()
    if df["reserved_qty"].isna().all():
        notes.append("No reserved quantities were provided: reserved stock is treated as 0.")
    elif df["reserved_qty"].isna().any():
        notes.append(f"{int(df['reserved_qty'].isna().sum())} SKUs have no reserved quantity: "
                     "treated as 0.")
    df["reserved_qty"] = df["reserved_qty"].fillna(0.0)
    return df.reset_index(drop=True)


def clean_sales(sales: pd.DataFrame, notes: list[str]) -> pd.DataFrame:
    """Aggregate to one row per SKU and day (revenue stays blank if never provided)."""
    if sales.empty:
        notes.append("No valid sales rows: demand-based analyses are not possible.")
        return pd.DataFrame(columns=["sku_id", "sale_date", "quantity_sold", "revenue"])
    grouped = sales.groupby(["sku_id", "sale_date"])
    # min_count=1 keeps revenue blank (NaN) when no revenue was recorded for that day
    daily = grouped[["quantity_sold", "revenue"]].sum(min_count=1)
    daily["records"] = grouped.size()
    daily = daily.reset_index()
    merged = int((daily["records"] > 1).sum())
    if merged:
        notes.append(f"{merged:,} SKU-days had several sales rows; they were summed into "
                     "daily totals.")
    return daily.drop(columns="records")


def build_dataset(validation, label: str, source_type: str, is_synthetic: bool) -> Dataset:
    """Create a Dataset from a usable DatasetValidation."""
    notes: list[str] = []
    files = validation.files
    pos = files.get("purchase_orders")
    purchase_orders = pos.clean.reset_index(drop=True) if pos is not None and pos.ok else None
    if purchase_orders is None:
        notes.append("No purchase-order file: incoming stock is assumed to be 0 and lead-time "
                     "variability can only come from the suppliers file.")
    return Dataset(
        products=clean_products(files["products"].clean, notes),
        sales=clean_sales(files["sales"].clean, notes),
        suppliers=files["suppliers"].clean.reset_index(drop=True),
        purchase_orders=purchase_orders,
        label=label, source_type=source_type, is_synthetic=is_synthetic,
        validation=validation, notes=notes,
    )
