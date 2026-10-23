-- Purpose : Daily sales of one SKU with a 7-day moving average. Days without a
--           sales record are filled with zero demand (generate_series), matching
--           the default "missing days = zero demand" policy of the dashboard.
-- Concepts: generate_series, LEFT JOIN, moving AVG() OVER (ROWS ...).
-- Params  : sku_id (text), start_date (date), end_date (date)
WITH calendar AS (
    SELECT d::date AS sale_date
    FROM generate_series(%(start_date)s::date, %(end_date)s::date, INTERVAL '1 day') AS d
), daily AS (
    SELECT c.sale_date, COALESCE(s.quantity_sold, 0) AS quantity_sold, s.revenue
    FROM calendar c
    LEFT JOIN sales_history s ON s.sale_date = c.sale_date AND s.sku_id = %(sku_id)s
)
SELECT sale_date,
       quantity_sold,
       revenue,
       ROUND(AVG(quantity_sold) OVER (ORDER BY sale_date
                                      ROWS BETWEEN 6 PRECEDING AND CURRENT ROW), 2) AS moving_avg_7d
FROM daily
ORDER BY sale_date;
