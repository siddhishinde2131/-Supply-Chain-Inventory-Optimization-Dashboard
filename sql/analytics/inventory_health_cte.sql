-- Purpose : Multi-step inventory health check: latest stock, average daily
--           demand, eligible incoming orders and days of cover, grouped into
--           coverage buckets. Incoming = open / in-transit orders without an
--           actual delivery date (same rule as the dashboard).
-- Concepts: several chained CTEs, CASE buckets, aggregation.
-- Params  : start_date (date), end_date (date)
WITH latest_snapshot AS (
    SELECT DISTINCT ON (sku_id) sku_id, on_hand_qty, reserved_qty
    FROM inventory_snapshots
    ORDER BY sku_id, snapshot_date DESC
), demand AS (
    SELECT sku_id,
           SUM(quantity_sold) / (%(end_date)s::date - %(start_date)s::date + 1) AS avg_daily_demand
    FROM sales_history
    WHERE sale_date BETWEEN %(start_date)s AND %(end_date)s
    GROUP BY sku_id
), incoming AS (
    SELECT sku_id, SUM(order_qty) AS incoming_qty
    FROM purchase_orders
    WHERE status IN ('open', 'in_transit') AND actual_delivery_date IS NULL
    GROUP BY sku_id
), health AS (
    SELECT p.sku_id, p.category,
           COALESCE(i.incoming_qty, 0)                                       AS incoming_qty,
           COALESCE(d.avg_daily_demand, 0)                                   AS avg_daily_demand,
           (s.on_hand_qty - s.reserved_qty) / NULLIF(d.avg_daily_demand, 0) AS days_of_cover,
           s.on_hand_qty * p.unit_cost                                       AS inventory_value
    FROM products p
    JOIN latest_snapshot s USING (sku_id)
    LEFT JOIN demand d USING (sku_id)
    LEFT JOIN incoming i USING (sku_id)
)
SELECT CASE WHEN avg_daily_demand = 0 THEN '5. No demand'
            WHEN days_of_cover <= 0   THEN '0. Out of stock'
            WHEN days_of_cover < 14   THEN '1. Under 2 weeks'
            WHEN days_of_cover < 60   THEN '2. 2 weeks to 2 months'
            WHEN days_of_cover < 180  THEN '3. 2 to 6 months'
            ELSE '4. Over 6 months' END AS coverage_bucket,
       COUNT(*)                         AS products,
       ROUND(SUM(inventory_value), 2)   AS inventory_value,
       SUM(incoming_qty)                AS incoming_units,
       ROUND(AVG(days_of_cover), 1)     AS avg_days_of_cover
FROM health
GROUP BY coverage_bucket
ORDER BY coverage_bucket;
