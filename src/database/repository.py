"""Reading and writing the dashboard data in PostgreSQL.

* ``create_schema``      runs sql/schema.sql (idempotent).
* ``save_dataset``       replaces the stored data with a validated Dataset in ONE
                         transaction (all or nothing).
* ``load_raw_frames``    reads the tables back as text frames, which then go
                         through the same validation and cleaning as CSV files.
* ``save_inventory_metrics`` stores the Python-calculated safety stock / ROP.
* ``run_query``          executes a file from sql/analytics with parameters.

All values are passed as query parameters or via COPY - never formatted into SQL.
"""
import io

import pandas as pd

from src.config import SQL_DIR
from src.data.cleaning import Dataset

TABLES_IN_DELETE_ORDER = ("inventory_metrics", "purchase_orders", "sales_history",
                          "inventory_snapshots", "products", "suppliers", "dataset_metadata")


def create_schema(conn) -> None:
    sql = (SQL_DIR / "schema.sql").read_text(encoding="utf-8")
    with conn.cursor() as cur:
        cur.execute(sql)


def schema_exists(conn) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM information_schema.tables "
                    "WHERE table_schema = current_schema() AND table_name = ANY(%s)",
                    (list(TABLES_IN_DELETE_ORDER),))
        return cur.fetchone()[0] == len(TABLES_IN_DELETE_ORDER)


def table_counts(conn) -> pd.DataFrame:
    rows = []
    with conn.cursor() as cur:
        for table in TABLES_IN_DELETE_ORDER:   # fixed names, not user input
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            rows.append({"table": table, "rows": cur.fetchone()[0]})
    return pd.DataFrame(rows)


def stored_dataset_info(conn) -> dict | None:
    with conn.cursor() as cur:
        cur.execute("SELECT label, is_synthetic, loaded_at FROM dataset_metadata WHERE id = 1")
        row = cur.fetchone()
    return None if row is None else {"label": row[0], "is_synthetic": row[1], "loaded_at": row[2]}


def _copy_frame(cur, frame: pd.DataFrame, table: str) -> None:
    """Bulk insert with COPY (fast for the ~500k sales rows)."""
    buffer = io.StringIO()
    frame.to_csv(buffer, index=False, header=False, date_format="%Y-%m-%d", na_rep="")
    buffer.seek(0)
    columns = ", ".join(frame.columns)
    cur.copy_expert(f"COPY {table} ({columns}) FROM STDIN WITH (FORMAT csv, NULL '')", buffer)


def check_referential_integrity(dataset: Dataset) -> list[str]:
    """Problems that PostgreSQL foreign keys would reject."""
    known = set(dataset.suppliers["supplier_id"])
    missing = sorted(set(dataset.products["supplier_id"]) - known)
    if missing:
        sample = ", ".join(missing[:5])
        return [f"{len(missing)} supplier ID(s) used by products are missing from the suppliers "
                f"file (e.g. {sample}). PostgreSQL enforces this relationship: add the suppliers "
                "or keep using CSV mode."]
    return []


def save_dataset(conn, dataset: Dataset) -> dict:
    """Replace all stored data with ``dataset``. Returns row counts written."""
    problems = check_referential_integrity(dataset)
    if problems:
        raise ValueError(" ".join(problems))
    p = dataset.products
    frames = {
        "suppliers": dataset.suppliers[["supplier_id", "supplier_name", "avg_lead_time_days",
                                        "lead_time_std_days"]],
        "products": p[["sku_id", "product_name", "category", "unit_cost", "selling_price",
                       "min_order_qty", "order_multiple", "supplier_id"]],
        "inventory_snapshots": p[["sku_id", "snapshot_date", "on_hand_qty", "reserved_qty"]],
        "sales_history": dataset.sales[["sale_date", "sku_id", "quantity_sold", "revenue"]],
    }
    if dataset.has_purchase_orders:
        frames["purchase_orders"] = dataset.purchase_orders[
            ["po_id", "sku_id", "order_qty", "order_date", "expected_delivery_date",
             "actual_delivery_date", "status"]]
    with conn.cursor() as cur:
        cur.execute("TRUNCATE " + ", ".join(TABLES_IN_DELETE_ORDER) + " RESTART IDENTITY")
        for table, frame in frames.items():
            _copy_frame(cur, frame, table)
        cur.execute("INSERT INTO dataset_metadata (id, label, is_synthetic) VALUES (1, %s, %s)",
                    (dataset.label, dataset.is_synthetic))
    return {table: len(frame) for table, frame in frames.items()}


def _as_text_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Convert DB values to text so they run through the normal CSV validation."""
    out = pd.DataFrame(index=frame.index)
    for col in frame.columns:
        s = frame[col]
        if pd.api.types.is_datetime64_any_dtype(s) or s.map(lambda v: hasattr(v, "isoformat")).any():
            s = pd.to_datetime(s).dt.strftime("%Y-%m-%d")
        out[col] = s.astype(object).where(s.notna(), None).map(
            lambda v: None if v is None else str(v))
    return out


def load_raw_frames(conn) -> dict[str, pd.DataFrame]:
    """Read the stored dataset as raw text frames keyed like the CSV files."""
    queries = {
        "products": """
            SELECT p.sku_id, p.product_name, p.category, p.unit_cost, p.selling_price,
                   s.on_hand_qty, s.reserved_qty, p.min_order_qty, p.order_multiple,
                   p.supplier_id, s.snapshot_date
            FROM products p
            JOIN (SELECT DISTINCT ON (sku_id) * FROM inventory_snapshots
                  ORDER BY sku_id, snapshot_date DESC) s USING (sku_id)
            ORDER BY p.sku_id""",
        "sales": "SELECT sale_date, sku_id, quantity_sold, revenue FROM sales_history "
                 "ORDER BY sale_date, sku_id",
        "suppliers": "SELECT supplier_id, supplier_name, avg_lead_time_days, lead_time_std_days "
                     "FROM suppliers ORDER BY supplier_id",
        "purchase_orders": "SELECT po_id, sku_id, order_qty, order_date, expected_delivery_date, "
                           "actual_delivery_date, status FROM purchase_orders ORDER BY po_id, sku_id",
    }
    frames = {}
    for key, sql in queries.items():
        frame = read_sql(conn, sql)
        if key == "purchase_orders" and frame.empty:
            continue           # optional file: absent rather than empty
        frames[key] = _as_text_frame(frame)
    return frames


def save_inventory_metrics(conn, plan: pd.DataFrame) -> int:
    cols = ["sku_id", "service_level", "avg_daily_demand", "std_daily_demand", "safety_stock",
            "reorder_point", "stock_position", "suggested_order_qty", "abc_class", "xyz_class",
            "alert_status"]
    frame = plan[cols].copy()
    for col in ("avg_daily_demand", "std_daily_demand", "safety_stock", "reorder_point",
                "stock_position"):
        frame[col] = frame[col].round(4)
    with conn.cursor() as cur:
        cur.execute("TRUNCATE inventory_metrics")
        _copy_frame(cur, frame, "inventory_metrics")
    return len(frame)


def read_sql(conn, sql: str, params: dict | None = None) -> pd.DataFrame:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        columns = [d[0] for d in cur.description]
        rows = cur.fetchall()
    frame = pd.DataFrame(rows, columns=columns)
    # NUMERIC columns arrive as Decimal; convert them to float for analysis/charts
    for col in frame.columns:
        if frame[col].map(lambda v: type(v).__name__ == "Decimal").any():
            frame[col] = pd.to_numeric(frame[col], errors="coerce")
    return frame


def run_query(conn, name: str, params: dict | None = None) -> pd.DataFrame:
    """Run sql/analytics/<name>.sql with named parameters."""
    path = SQL_DIR / "analytics" / f"{name}.sql"
    if not path.exists():
        raise FileNotFoundError(f"Unknown query '{name}'.")
    return read_sql(conn, path.read_text(encoding="utf-8"), params or {})
