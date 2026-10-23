-- =====================================================================
-- Supply Chain & Inventory Optimization Dashboard - PostgreSQL schema
-- Safe to run repeatedly (IF NOT EXISTS). Run from the app ("Create
-- tables") or with:  psql -d inventory_dashboard -f sql/schema.sql
-- =====================================================================

-- Suppliers and their agreed lead times
CREATE TABLE IF NOT EXISTS suppliers (
    supplier_id         VARCHAR(50)  PRIMARY KEY,
    supplier_name       VARCHAR(200) NOT NULL,
    avg_lead_time_days  NUMERIC(8,2) NOT NULL CHECK (avg_lead_time_days > 0 AND avg_lead_time_days <= 365),
    lead_time_std_days  NUMERIC(8,2)          CHECK (lead_time_std_days >= 0)
);

-- Product master data
CREATE TABLE IF NOT EXISTS products (
    sku_id          VARCHAR(50)   PRIMARY KEY,
    product_name    VARCHAR(300)  NOT NULL,
    category        VARCHAR(100)  NOT NULL,
    unit_cost       NUMERIC(14,4) NOT NULL CHECK (unit_cost > 0),
    selling_price   NUMERIC(14,4) NOT NULL CHECK (selling_price > 0),
    min_order_qty   NUMERIC(14,2)          CHECK (min_order_qty > 0),
    order_multiple  NUMERIC(14,2)          CHECK (order_multiple > 0),
    supplier_id     VARCHAR(50)   NOT NULL REFERENCES suppliers (supplier_id)
);
CREATE INDEX IF NOT EXISTS ix_products_category ON products (category);
CREATE INDEX IF NOT EXISTS ix_products_supplier ON products (supplier_id);

-- Stock counts (one row per SKU and snapshot date)
CREATE TABLE IF NOT EXISTS inventory_snapshots (
    sku_id         VARCHAR(50)   NOT NULL REFERENCES products (sku_id) ON DELETE CASCADE,
    snapshot_date  DATE          NOT NULL,
    on_hand_qty    NUMERIC(14,2) NOT NULL CHECK (on_hand_qty >= 0),
    reserved_qty   NUMERIC(14,2) NOT NULL DEFAULT 0 CHECK (reserved_qty >= 0),
    PRIMARY KEY (sku_id, snapshot_date)
);

-- Daily sales history (one row per SKU and day after cleaning)
CREATE TABLE IF NOT EXISTS sales_history (
    sale_id        BIGSERIAL     PRIMARY KEY,
    sale_date      DATE          NOT NULL,
    sku_id         VARCHAR(50)   NOT NULL REFERENCES products (sku_id) ON DELETE CASCADE,
    quantity_sold  NUMERIC(14,2) NOT NULL CHECK (quantity_sold >= 0),
    revenue        NUMERIC(16,2)          CHECK (revenue >= 0),
    UNIQUE (sku_id, sale_date)
);
CREATE INDEX IF NOT EXISTS ix_sales_date ON sales_history (sale_date);

-- Purchase orders (one row per order line)
CREATE TABLE IF NOT EXISTS purchase_orders (
    po_id                   VARCHAR(50)   NOT NULL,
    sku_id                  VARCHAR(50)   NOT NULL REFERENCES products (sku_id) ON DELETE CASCADE,
    order_qty               NUMERIC(14,2) NOT NULL CHECK (order_qty > 0),
    order_date              DATE          NOT NULL,
    expected_delivery_date  DATE          NOT NULL,
    actual_delivery_date    DATE,
    status                  VARCHAR(20)   NOT NULL
        CHECK (status IN ('open', 'in_transit', 'received', 'cancelled')),
    PRIMARY KEY (po_id, sku_id),
    CHECK (expected_delivery_date >= order_date),
    CHECK (actual_delivery_date IS NULL OR actual_delivery_date >= order_date)
);
CREATE INDEX IF NOT EXISTS ix_po_sku_status ON purchase_orders (sku_id, status);

-- Results calculated in Python (single source of the inventory formulas).
-- Lets SQL queries such as "products below reorder point" use the same numbers.
CREATE TABLE IF NOT EXISTS inventory_metrics (
    sku_id              VARCHAR(50)   PRIMARY KEY REFERENCES products (sku_id) ON DELETE CASCADE,
    service_level       NUMERIC(6,4)  NOT NULL,
    avg_daily_demand    NUMERIC(16,4),
    std_daily_demand    NUMERIC(16,4),
    safety_stock        NUMERIC(16,4),
    reorder_point       NUMERIC(16,4),
    stock_position      NUMERIC(16,4),
    suggested_order_qty NUMERIC(16,2),
    abc_class           VARCHAR(20),
    xyz_class           VARCHAR(20),
    alert_status        VARCHAR(40),
    calculated_at       TIMESTAMP     NOT NULL DEFAULT NOW()
);

-- Describes the dataset currently stored (e.g. synthetic sample or user upload)
CREATE TABLE IF NOT EXISTS dataset_metadata (
    id            SMALLINT     PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    label         VARCHAR(200) NOT NULL,
    is_synthetic  BOOLEAN      NOT NULL,
    loaded_at     TIMESTAMP    NOT NULL DEFAULT NOW()
);
