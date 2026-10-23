"""Reproducible SYNTHETIC sample dataset.

The generator uses a fixed random seed, so the same files are produced every time.
Files are written once to ``data/sample/`` and re-used on later runs; the dashboard
never regenerates them on a rerun.

Run directly to (re)create the files:
    python -m src.data.sample_generator
"""
from pathlib import Path

import numpy as np
import pandas as pd

from src.config import SAMPLE_DIR
from src.data.schema import FILE_SPECS

SAMPLE_FILES = {
    "products": "products.csv",
    "sales": "sales.csv",
    "suppliers": "suppliers.csv",
    "purchase_orders": "purchase_orders.csv",
}

SEED = 42
N_SKUS = 2400
HISTORY_START = "2025-10-01"
HISTORY_DAYS = 365

# category -> (median unit cost, product nouns)
CATEGORIES = {
    "Electronics": (60.0, ["Headphones", "Charger", "Speaker", "Keyboard", "Webcam", "Router"]),
    "Home & Kitchen": (18.0, ["Pan", "Knife Set", "Kettle", "Storage Box", "Towel", "Lamp"]),
    "Apparel": (14.0, ["T-Shirt", "Jacket", "Socks", "Cap", "Jeans", "Scarf"]),
    "Beauty": (8.0, ["Shampoo", "Lotion", "Lip Balm", "Face Wash", "Serum", "Soap"]),
    "Grocery": (3.0, ["Rice", "Pasta", "Coffee", "Tea", "Olive Oil", "Cereal"]),
    "Toys": (12.0, ["Puzzle", "Building Set", "Doll", "Board Game", "RC Car", "Plush"]),
    "Sports": (25.0, ["Yoga Mat", "Dumbbell", "Football", "Water Bottle", "Racket", "Gloves"]),
    "Office Supplies": (4.0, ["Notebook", "Pen Pack", "Stapler", "Folder", "Marker", "Tape"]),
    "Automotive": (22.0, ["Wiper", "Car Wax", "Floor Mat", "Air Filter", "Jump Cable", "Bulb"]),
    "Health": (9.0, ["Vitamins", "Bandages", "Thermometer", "Hand Gel", "Mask Pack", "Pain Relief"]),
}
NAME_PREFIXES = ["Apex", "Summit", "Harbor", "Pioneer", "Evergreen",
                 "Bluewave", "Crescent", "Ironwood", "Lakeside", "Meridian"]
NAME_SUFFIXES = ["Supply Co", "Distribution", "Wholesale", "Trading"]
PRODUCT_ADJECTIVES = ["Classic", "Premium", "Eco", "Compact", "Pro", "Ultra", "Basic", "Smart"]


def _suppliers(rng: np.random.Generator) -> pd.DataFrame:
    names = [f"{p} {s} (Synthetic)" for s in NAME_SUFFIXES for p in NAME_PREFIXES]
    n = len(names)
    avg_lt = rng.integers(3, 46, n).astype(float)
    std_lt = np.round(avg_lt * rng.uniform(0.08, 0.35, n), 1)
    # A few suppliers do not report lead-time variability: the app must estimate it
    # from purchase-order history or fall back to the fixed-lead-time model.
    std_lt[rng.choice(n, 6, replace=False)] = np.nan
    return pd.DataFrame({
        "supplier_id": [f"SUP-{i + 1:03d}" for i in range(n)],
        "supplier_name": names,
        "avg_lead_time_days": avg_lt,
        "lead_time_std_days": std_lt,
    })


def _products(rng: np.random.Generator, suppliers: pd.DataFrame) -> pd.DataFrame:
    cats = list(CATEGORIES)
    category = rng.choice(cats, N_SKUS, p=np.full(len(cats), 1 / len(cats)))
    median_cost = np.array([CATEGORIES[c][0] for c in category])
    unit_cost = np.round(np.clip(median_cost * rng.lognormal(0, 0.7, N_SKUS), 0.5, 900), 2)
    selling_price = np.round(unit_cost * rng.uniform(1.25, 2.3, N_SKUS), 2)
    names = [
        f"{rng.choice(PRODUCT_ADJECTIVES)} {rng.choice(CATEGORIES[c][1])} {i + 1:04d}"
        for i, c in enumerate(category)
    ]
    moq = np.where(rng.random(N_SKUS) < 0.40, rng.choice([10, 20, 25, 50, 100], N_SKUS), np.nan)
    multiple = np.where(rng.random(N_SKUS) < 0.35, rng.choice([6, 12, 24, 48], N_SKUS), np.nan)
    return pd.DataFrame({
        "sku_id": [f"SKU-{i + 1:05d}" for i in range(N_SKUS)],
        "product_name": names,
        "category": category,
        "unit_cost": unit_cost,
        "selling_price": selling_price,
        "min_order_qty": moq,
        "order_multiple": multiple,
        "supplier_id": rng.choice(suppliers["supplier_id"].to_numpy(), N_SKUS),
    })


def _demand_matrix(rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
    """Return (daily demand matrix [sku x day], base daily rate per SKU)."""
    t = np.arange(HISTORY_DAYS)
    base = np.clip(rng.lognormal(np.log(3.0), 1.1, N_SKUS), 0.05, 250)
    pattern = rng.choice(["stable", "seasonal", "intermittent", "trending", "dead"],
                         N_SKUS, p=[0.40, 0.20, 0.25, 0.10, 0.05])
    weekday = pd.date_range(HISTORY_START, periods=HISTORY_DAYS).dayofweek.to_numpy()
    weekly = np.where(weekday >= 5, 1.25, 0.92)                      # weekend uplift
    lam = np.outer(base, weekly)

    seasonal = pattern == "seasonal"
    phase = rng.uniform(0, 2 * np.pi, seasonal.sum())
    lam[seasonal] *= 1 + 0.6 * np.sin(2 * np.pi * t / 365 + phase[:, None])

    trending = pattern == "trending"
    growth = rng.uniform(-0.6, 1.0, trending.sum())
    lam[trending] *= np.clip(1 + growth[:, None] * t / 365, 0.1, None)

    demand = rng.poisson(lam).astype(float)

    intermittent = pattern == "intermittent"
    p_sale = rng.uniform(0.04, 0.30, intermittent.sum())
    occurs = rng.random((intermittent.sum(), HISTORY_DAYS)) < p_sale[:, None]
    size = rng.poisson((base[intermittent] / p_sale)[:, None] + 1,
                       (intermittent.sum(), HISTORY_DAYS))
    demand[intermittent] = np.where(occurs, size, 0)

    demand[pattern == "dead"] = 0          # products with no sales in the period
    expected_rate = demand.mean(axis=1)
    return demand, expected_rate


def _inventory(rng, products, suppliers, rate, snapshot_date) -> tuple[pd.DataFrame, np.ndarray]:
    lead = products["supplier_id"].map(suppliers.set_index("supplier_id")["avg_lead_time_days"])
    lead = lead.to_numpy()
    segment = rng.choice(["stockout", "low", "normal", "excess"], N_SKUS,
                         p=[0.06, 0.22, 0.50, 0.22])
    cover = np.select(
        [segment == "stockout", segment == "low", segment == "normal"],
        [0, lead * rng.uniform(0.2, 1.0, N_SKUS), lead + rng.uniform(10, 50, N_SKUS)],
        default=rng.uniform(150, 450, N_SKUS),
    )
    on_hand = np.round(rate * cover)
    dead = rate == 0
    on_hand[dead] = rng.integers(0, 300, dead.sum())       # stock with no demand
    reserved = np.where(rng.random(N_SKUS) < 0.30, np.floor(on_hand * rng.uniform(0, 0.15, N_SKUS)), 0)
    reserved = np.where(rng.random(N_SKUS) < 0.5, reserved, np.nan)  # sometimes not recorded
    inv = products.copy()
    inv["on_hand_qty"] = on_hand
    inv["reserved_qty"] = reserved
    inv["snapshot_date"] = snapshot_date.strftime("%Y-%m-%d")
    return inv, segment


def _purchase_orders(rng, products, suppliers, rate, segment, snapshot_date) -> pd.DataFrame:
    sup = suppliers.set_index("supplier_id")
    # Hidden "true" behaviour: some suppliers deliver later than they state.
    unreliable = set(rng.choice(sup.index.to_numpy(), 8, replace=False))
    rows = []
    start = pd.Timestamp(HISTORY_START)
    po_no = 1
    for i, row in products.iterrows():
        s = sup.loc[row["supplier_id"]]
        stated = s["avg_lead_time_days"]
        true_std = s["lead_time_std_days"] if pd.notna(s["lead_time_std_days"]) else stated * 0.25
        # Reliable suppliers quote a slightly padded lead time (~84% of orders on time);
        # unreliable ones are 30% slower than stated.
        true_mean = stated * 1.3 if row["supplier_id"] in unreliable else max(1.0, stated - true_std)
        qty = max(1.0, round(rate[i] * 30))
        # Historical, received (or cancelled) orders spread over the year.
        for _ in range(rng.poisson(3) if rate[i] > 0 else 0):
            order = start + pd.Timedelta(days=int(rng.integers(0, HISTORY_DAYS - 80)))
            actual_lt = max(1, int(round(rng.normal(true_mean, true_std))))
            cancelled = rng.random() < 0.04
            rows.append({
                "po_id": f"PO-{po_no:06d}", "sku_id": row["sku_id"], "order_qty": qty,
                "order_date": order,
                "expected_delivery_date": order + pd.Timedelta(days=int(stated)),
                "actual_delivery_date": pd.NaT if cancelled else order + pd.Timedelta(days=actual_lt),
                "status": "cancelled" if cancelled else "received",
            })
            po_no += 1
        # Open / in-transit orders, mostly for low-stock items.
        p_open = 0.55 if segment[i] in ("low", "stockout") else 0.05
        if rate[i] > 0 and rng.random() < p_open:
            order = snapshot_date - pd.Timedelta(days=int(rng.integers(0, max(1, stated))))
            rows.append({
                "po_id": f"PO-{po_no:06d}", "sku_id": row["sku_id"],
                "order_qty": max(1.0, round(rate[i] * rng.uniform(15, 45))),
                "order_date": order,
                "expected_delivery_date": order + pd.Timedelta(days=int(stated)),
                "actual_delivery_date": pd.NaT,
                "status": "in_transit" if rng.random() < 0.5 else "open",
            })
            po_no += 1
    pos = pd.DataFrame(rows)
    for col in ("order_date", "expected_delivery_date", "actual_delivery_date"):
        pos[col] = pd.to_datetime(pos[col]).dt.strftime("%Y-%m-%d")
    return pos


def _sales(rng, products, demand) -> pd.DataFrame:
    dates = pd.date_range(HISTORY_START, periods=HISTORY_DAYS)
    sku_idx, day_idx = np.nonzero(demand)
    qty = demand[sku_idx, day_idx]
    price = products["selling_price"].to_numpy()[sku_idx]
    sales = pd.DataFrame({
        "sale_date": dates[day_idx].strftime("%Y-%m-%d"),
        "sku_id": products["sku_id"].to_numpy()[sku_idx],
        "quantity_sold": qty,
        "revenue": np.round(qty * price * rng.uniform(0.90, 1.0, len(qty)), 2),
    })
    # Deliberate data-quality problems so the validation report has something to show:
    # exact duplicate rows and negative quantities (both are reported and excluded).
    dupes = sales.sample(30, random_state=SEED)
    negatives = sales.sample(6, random_state=SEED + 1).assign(
        quantity_sold=lambda d: -d["quantity_sold"])
    sales = pd.concat([sales, dupes, negatives], ignore_index=True)
    return sales.sort_values(["sale_date", "sku_id"], kind="stable").reset_index(drop=True)


def generate_sample_data(output_dir: Path = SAMPLE_DIR) -> dict[str, Path]:
    """Generate the synthetic dataset and write it as CSV files. Returns the file paths."""
    rng = np.random.default_rng(SEED)
    snapshot_date = pd.Timestamp(HISTORY_START) + pd.Timedelta(days=HISTORY_DAYS - 1)
    suppliers = _suppliers(rng)
    products = _products(rng, suppliers)
    demand, rate = _demand_matrix(rng)
    inventory, segment = _inventory(rng, products, suppliers, rate, snapshot_date)
    purchase_orders = _purchase_orders(rng, products, suppliers, rate, segment, snapshot_date)
    sales = _sales(rng, products, demand)

    output_dir.mkdir(parents=True, exist_ok=True)
    frames = {"products": inventory, "sales": sales, "suppliers": suppliers,
              "purchase_orders": purchase_orders}
    whole_numbers = ["on_hand_qty", "reserved_qty", "min_order_qty", "order_multiple",
                     "quantity_sold", "order_qty", "avg_lead_time_days"]
    paths = {}
    for key, frame in frames.items():
        frame = frame[FILE_SPECS[key].column_names].copy()   # schema column order
        for col in frame.columns.intersection(whole_numbers):
            frame[col] = frame[col].round().astype("Int64")
        path = output_dir / SAMPLE_FILES[key]
        frame.to_csv(path, index=False)
        paths[key] = path
    return paths


def sample_files_exist(output_dir: Path = SAMPLE_DIR) -> bool:
    return all((output_dir / name).exists() for name in SAMPLE_FILES.values())


def ensure_sample_data(output_dir: Path = SAMPLE_DIR) -> dict[str, Path]:
    """Create the sample files only if they do not exist yet."""
    if not sample_files_exist(output_dir):
        return generate_sample_data(output_dir)
    return {key: output_dir / name for key, name in SAMPLE_FILES.items()}


if __name__ == "__main__":
    for name, file_path in generate_sample_data().items():
        print(f"{name:16s} -> {file_path}")
