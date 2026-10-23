-- Purpose : Highest-value products in stock with their rank and the running
--           (cumulative) share of total inventory value.
-- Concepts: CTE, RANK(), running SUM() OVER (ORDER BY ...).
-- Params  : limit (integer) - number of products to return
WITH latest_snapshot AS (
    SELECT DISTINCT ON (sku_id) sku_id, on_hand_qty
    FROM inventory_snapshots
    ORDER BY sku_id, snapshot_date DESC
), valued AS (
    SELECT p.sku_id, p.product_name, p.category, p.supplier_id, s.on_hand_qty, p.unit_cost,
           s.on_hand_qty * p.unit_cost AS inventory_value
    FROM latest_snapshot s
    JOIN products p USING (sku_id)
)
SELECT RANK() OVER (ORDER BY inventory_value DESC) AS value_rank,
       valued.*,
       ROUND(SUM(inventory_value) OVER (ORDER BY inventory_value DESC, sku_id
                                        ROWS UNBOUNDED PRECEDING)
             / NULLIF(SUM(inventory_value) OVER (), 0), 4) AS cumulative_share
FROM valued
ORDER BY value_rank, sku_id
LIMIT %(limit)s;
