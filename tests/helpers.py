"""Build tiny datasets from CSV text for tests."""
import pandas as pd

from src.data.loader import dataset_from_sources


def csv(text: str) -> bytes:
    return "\n".join(line.strip() for line in text.strip().splitlines()).encode("utf-8")


def daily_sales(sku: str, quantities, start: str = "2026-01-01") -> str:
    """Sales CSV rows (no header) for consecutive days; None = no record that day."""
    days = pd.date_range(start, periods=len(quantities))
    return "\n".join(f"{d:%Y-%m-%d},{sku},{q}" for d, q in zip(days, quantities) if q is not None)


def build(products: str, sales_rows: str, suppliers: str, purchase_orders: str | None = None):
    sources = {
        "products": csv(products),
        "sales": csv("sale_date,sku_id,quantity_sold\n" + sales_rows),
        "suppliers": csv(suppliers),
    }
    if purchase_orders is not None:
        sources["purchase_orders"] = csv(purchase_orders)
    return dataset_from_sources(sources, "Test dataset", "upload_csv")
