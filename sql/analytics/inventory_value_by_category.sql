-- Purpose : Inventory units and value per category, using the latest stock
--           snapshot of each SKU. Inventory value = on-hand qty x unit cost.
-- Concepts: CTE, DISTINCT ON, JOIN, GROUP BY, window function over the totals.
-- Params  : none
WITH latest_snapshot AS (
    SELECT DISTINCT ON (sku_id) sku_id, on_hand_qty, reserved_qty
    FROM inventory_snapshots
    ORDER BY sku_id, snapshot_date DESC
)
SELECT p.category,
       COUNT(*)                                        AS products,
       SUM(s.on_hand_qty)                              AS on_hand_units,
       ROUND(SUM(s.on_hand_qty * p.unit_cost), 2)      AS inventory_value,
       ROUND(SUM(s.on_hand_qty * p.unit_cost)
             / NULLIF(SUM(SUM(s.on_hand_qty * p.unit_cost)) OVER (), 0), 4) AS share_of_inventory_value
FROM latest_snapshot s
JOIN products p USING (sku_id)
GROUP BY p.category
ORDER BY inventory_value DESC;
