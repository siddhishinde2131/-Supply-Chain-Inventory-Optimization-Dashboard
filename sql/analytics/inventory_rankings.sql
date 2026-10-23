-- Purpose : Rank products by inventory value within their category and
--           overall (percentile, quartile) to see where capital is concentrated.
-- Concepts: RANK, DENSE_RANK, PERCENT_RANK, NTILE, PARTITION BY.
-- Params  : max_rank_in_category (integer) - keep the top N per category
WITH latest_snapshot AS (
    SELECT DISTINCT ON (sku_id) sku_id, on_hand_qty
    FROM inventory_snapshots
    ORDER BY sku_id, snapshot_date DESC
), valued AS (
    SELECT p.sku_id, p.product_name, p.category, s.on_hand_qty, p.unit_cost,
           s.on_hand_qty * p.unit_cost AS inventory_value
    FROM latest_snapshot s
    JOIN products p USING (sku_id)
), ranked AS (
    SELECT valued.*,
           RANK()       OVER (PARTITION BY category ORDER BY inventory_value DESC) AS rank_in_category,
           DENSE_RANK() OVER (ORDER BY inventory_value DESC)                       AS overall_dense_rank,
           ROUND(PERCENT_RANK() OVER (ORDER BY inventory_value)::numeric, 4)        AS value_percentile,
           NTILE(4)     OVER (ORDER BY inventory_value DESC)                       AS value_quartile
    FROM valued
)
SELECT *
FROM ranked
WHERE rank_in_category <= %(max_rank_in_category)s
ORDER BY category, rank_in_category;
