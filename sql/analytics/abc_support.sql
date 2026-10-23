-- Purpose : ABC classification support. Consumption value per SKU and the
--           cumulative share of value of the products ranked BEFORE each SKU,
--           which is exactly the rule used in src/analytics/classification.py.
-- Concepts: CTE, ROW_NUMBER, running SUM() OVER with a frame ending at
--           1 PRECEDING, CASE.
-- Params  : start_date, end_date (date), annual_factor (numeric),
--           a_threshold, b_threshold (numeric, e.g. 0.80 and 0.95)
WITH consumption AS (
    SELECT p.sku_id, p.category, p.unit_cost,
           COALESCE(SUM(s.quantity_sold), 0)                                   AS period_qty,
           COALESCE(SUM(s.quantity_sold), 0) * p.unit_cost * %(annual_factor)s AS annual_consumption_value
    FROM products p
    LEFT JOIN sales_history s
           ON s.sku_id = p.sku_id AND s.sale_date BETWEEN %(start_date)s AND %(end_date)s
    GROUP BY p.sku_id, p.category, p.unit_cost
), ranked AS (
    SELECT c.*,
           ROW_NUMBER() OVER (ORDER BY annual_consumption_value DESC, sku_id) AS abc_rank,
           COALESCE(SUM(annual_consumption_value) OVER (
               ORDER BY annual_consumption_value DESC, sku_id
               ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING), 0)
             / NULLIF(SUM(annual_consumption_value) OVER (), 0)             AS cumulative_share_before
    FROM consumption c
)
SELECT sku_id, category, period_qty,
       ROUND(annual_consumption_value, 2)  AS annual_consumption_value,
       abc_rank,
       ROUND(cumulative_share_before, 6)   AS cumulative_share_before,
       CASE WHEN annual_consumption_value <= 0 OR cumulative_share_before IS NULL THEN 'C'
            WHEN cumulative_share_before < %(a_threshold)s THEN 'A'
            WHEN cumulative_share_before < %(b_threshold)s THEN 'B'
            ELSE 'C' END                   AS abc_class
FROM ranked
ORDER BY abc_rank;
