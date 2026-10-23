"""Definition of the four supported input files.

This module is the single source of truth for column names, data types, which
fields are mandatory, and the value rules. Validation, CSV templates, the sample
generator and the database loader all use it.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Column:
    name: str
    dtype: str                 # "text", "number" or "date"
    required: bool             # True = column must exist and every value must be filled
    description: str
    example: str
    min_value: float | None = None   # smallest allowed number
    strictly_positive: bool = False  # True = value must be > min_value (e.g. > 0)
    max_value: float | None = None
    allowed: tuple[str, ...] | None = None  # allowed text values (after normalising)


@dataclass(frozen=True)
class FileSpec:
    key: str
    label: str
    required: bool             # is the whole file mandatory?
    description: str
    columns: tuple[Column, ...]
    key_columns: tuple[str, ...] = ()   # combination that must be unique

    @property
    def column_names(self) -> list[str]:
        return [c.name for c in self.columns]

    @property
    def required_columns(self) -> list[str]:
        return [c.name for c in self.columns if c.required]

    def column(self, name: str) -> Column:
        return next(c for c in self.columns if c.name == name)


PO_STATUSES = ("open", "in_transit", "received", "cancelled")
INCOMING_PO_STATUSES = ("open", "in_transit")

PRODUCTS = FileSpec(
    key="products",
    label="Products & Inventory",
    required=True,
    description="One row per SKU: product master data plus the current stock snapshot.",
    key_columns=("sku_id",),
    columns=(
        Column("sku_id", "text", True, "Unique product identifier.", "SKU-00001"),
        Column("product_name", "text", True, "Product name.", "Wireless Mouse"),
        Column("category", "text", True, "Product category.", "Electronics"),
        Column("unit_cost", "number", True, "Purchase cost per unit (> 0).", "12.50",
               min_value=0, strictly_positive=True),
        Column("selling_price", "number", True, "Selling price per unit (> 0).", "24.99",
               min_value=0, strictly_positive=True),
        Column("on_hand_qty", "number", True, "Physical units in stock (>= 0).", "140",
               min_value=0),
        Column("reserved_qty", "number", False,
               "Units already promised to customers (>= 0). Blank = 0.", "10", min_value=0),
        Column("min_order_qty", "number", False,
               "Minimum order quantity (> 0). Blank = no minimum.", "50",
               min_value=0, strictly_positive=True),
        Column("order_multiple", "number", False,
               "Orders must be a multiple of this pack size (> 0). Blank = 1.", "12",
               min_value=0, strictly_positive=True),
        Column("supplier_id", "text", True, "Supplier that replenishes this SKU.", "SUP-001"),
        Column("snapshot_date", "date", True, "Date of the stock count (YYYY-MM-DD).",
               "2026-09-30"),
    ),
)

SALES = FileSpec(
    key="sales",
    label="Sales History",
    required=True,
    description="Daily (or transaction-level) units sold per SKU. Several rows for the "
                "same SKU and date are added together.",
    columns=(
        Column("sale_date", "date", True, "Date of sale (YYYY-MM-DD).", "2026-09-29"),
        Column("sku_id", "text", True, "SKU sold. Must exist in the products file.",
               "SKU-00001"),
        Column("quantity_sold", "number", True, "Units sold (>= 0).", "3", min_value=0),
        Column("revenue", "number", False, "Sales revenue (>= 0). Optional.", "74.97",
               min_value=0),
    ),
)

SUPPLIERS = FileSpec(
    key="suppliers",
    label="Suppliers & Lead Times",
    required=True,
    description="One row per supplier with the average replenishment lead time.",
    key_columns=("supplier_id",),
    columns=(
        Column("supplier_id", "text", True, "Unique supplier identifier.", "SUP-001"),
        Column("supplier_name", "text", True, "Supplier name.", "Example Supplies Ltd"),
        Column("avg_lead_time_days", "number", True,
               "Average days from order to delivery (> 0, <= 365).", "14",
               min_value=0, strictly_positive=True, max_value=365),
        Column("lead_time_std_days", "number", False,
               "Standard deviation of lead time in days (>= 0). Blank = estimate from "
               "purchase-order history if available.", "3", min_value=0, max_value=365),
    ),
)

PURCHASE_ORDERS = FileSpec(
    key="purchase_orders",
    label="Purchase Orders",
    required=False,
    description="Optional. Open and historical purchase orders. Open / in-transit orders "
                "count as incoming stock; received orders provide lead-time observations.",
    key_columns=("po_id", "sku_id"),
    columns=(
        Column("po_id", "text", True, "Purchase order number.", "PO-000123"),
        Column("sku_id", "text", True, "SKU ordered. Must exist in the products file.",
               "SKU-00001"),
        Column("order_qty", "number", True, "Units ordered (> 0).", "200",
               min_value=0, strictly_positive=True),
        Column("order_date", "date", True, "Date the order was placed (YYYY-MM-DD).",
               "2026-09-20"),
        Column("expected_delivery_date", "date", True,
               "Promised delivery date (YYYY-MM-DD).", "2026-10-04"),
        Column("actual_delivery_date", "date", False,
               "Date actually received (YYYY-MM-DD). Blank if not yet received.", ""),
        Column("status", "text", True,
               "One of: open, in_transit, received, cancelled.", "open",
               allowed=PO_STATUSES),
    ),
)

FILE_SPECS: dict[str, FileSpec] = {
    spec.key: spec for spec in (PRODUCTS, SALES, SUPPLIERS, PURCHASE_ORDERS)
}

# Common alternative column names that are mapped automatically to the schema.
COLUMN_ALIASES = {
    "sku": "sku_id", "product_id": "sku_id", "item_id": "sku_id",
    "name": "product_name", "product": "product_name",
    "cost": "unit_cost", "price": "selling_price", "unit_price": "selling_price",
    "on_hand": "on_hand_qty", "stock": "on_hand_qty", "quantity_on_hand": "on_hand_qty",
    "reserved": "reserved_qty", "moq": "min_order_qty", "pack_size": "order_multiple",
    "date": "sale_date", "qty": "quantity_sold", "quantity": "quantity_sold",
    "units_sold": "quantity_sold", "sales_revenue": "revenue",
    "lead_time_days": "avg_lead_time_days", "lead_time": "avg_lead_time_days",
    "lead_time_std": "lead_time_std_days",
    "purchase_order_id": "po_id", "order_quantity": "order_qty", "quantity_ordered": "order_qty",
    "order_status": "status",
}


def template_csv(spec: FileSpec) -> bytes:
    """Header plus one example row, generated from the schema itself."""
    header = ",".join(spec.column_names)
    example = ",".join(c.example for c in spec.columns)
    return f"{header}\n{example}\n".encode("utf-8")


def schema_table(spec: FileSpec) -> list[dict]:
    """Column documentation rows (for the Home page and README)."""
    return [{"column": c.name, "type": c.dtype, "mandatory": "Yes" if c.required else "Optional",
             "description": c.description, "example": c.example} for c in spec.columns]


def normalise_column_name(name: str) -> str:
    """'On Hand Qty ' -> 'on_hand_qty', then apply known aliases."""
    clean = str(name).strip().lower().replace("-", "_").replace(" ", "_")
    while "__" in clean:
        clean = clean.replace("__", "_")
    return COLUMN_ALIASES.get(clean, clean)


def normalise_status(value: str) -> str:
    """'In Transit' / 'in-transit' -> 'in_transit'; 'canceled' -> 'cancelled'."""
    clean = str(value).strip().lower().replace("-", "_").replace(" ", "_")
    return "cancelled" if clean == "canceled" else clean
