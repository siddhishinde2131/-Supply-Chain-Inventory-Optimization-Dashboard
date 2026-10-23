-- Purpose : Demand statistics per SKU over the analysis window. Days without a
--           sales record count as zero demand, so the mean and the SAMPLE
--           standard deviation equal the Python calculation in
--           src/analytics/demand.py (used for the reconciliation check).
-- Concepts: CTE, aggregation, FILTER, LEFT JOIN to keep SKUs without sales.
-- Params  : start_date (date), end_date (date)
WITH window_days AS (
    SELECT (%(end_date)s::date - %(start_date)s::date + 1)::numeric AS n
), sku_sales AS (
    SELECT sku_id,
           SUM(quantity_sold)                        AS total_qty,
           SUM(quantity_sold * quantity_sold)        AS sum_sq,
           COUNT(*) FILTER (WHERE quantity_sold > 0) AS days_with_sales
    FROM sales_history
    WHERE sale_date BETWEEN %(start_date)s AND %(end_date)s
    GROUP BY sku_id
)
SELECT p.sku_id, p.product_name, p.category,
       COALESCE(s.total_qty, 0)                        AS total_qty,
       COALESCE(s.days_with_sales, 0)                  AS days_with_sales,
       ROUND(COALESCE(s.total_qty, 0) / w.n, 4)        AS avg_daily_demand,
       ROUND(SQRT(GREATEST(
           (COALESCE(s.sum_sq, 0) - w.n * POWER(COALESCE(s.total_qty, 0) / w.n, 2))
           / NULLIF(w.n - 1, 0), 0)), 4)               AS std_daily_demand
FROM products p
CROSS JOIN window_days w
LEFT JOIN sku_sales s USING (sku_id)
ORDER BY total_qty DESC, p.sku_id;
