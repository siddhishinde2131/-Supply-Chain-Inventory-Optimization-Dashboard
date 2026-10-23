-- Purpose : Products whose stock position is at or below the reorder point.
--           Safety stock and reorder points are calculated once in Python
--           (src/inventory/formulas.py) and stored in inventory_metrics, so SQL
--           and the dashboard always use the same formula.
-- Concepts: JOIN, derived columns, ORDER BY a calculated value.
-- Params  : limit (integer)
SELECT m.sku_id, p.product_name, p.category, p.supplier_id,
       m.abc_class, m.xyz_class,
       ROUND(m.stock_position, 2)                    AS stock_position,
       ROUND(m.safety_stock, 2)                      AS safety_stock,
       ROUND(m.reorder_point, 2)                     AS reorder_point,
       ROUND(m.reorder_point - m.stock_position, 2)  AS gap_to_reorder_point,
       m.suggested_order_qty,
       ROUND(m.suggested_order_qty * p.unit_cost, 2) AS estimated_order_cost,
       m.service_level, m.calculated_at
FROM inventory_metrics m
JOIN products p USING (sku_id)
WHERE m.reorder_point IS NOT NULL
  AND m.alert_status = 'Reorder Required'
  AND m.stock_position <= m.reorder_point
ORDER BY (m.reorder_point - m.stock_position) * p.unit_cost DESC
LIMIT %(limit)s;
