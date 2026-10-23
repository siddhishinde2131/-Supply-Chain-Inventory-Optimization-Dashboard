-- Purpose : Stated vs observed supplier lead times from received purchase
--           orders, lead-time variability and on-time delivery rate.
-- Concepts: CTE, date arithmetic, STDDEV_SAMP, LEFT JOIN, GROUP BY.
-- Params  : none
WITH received AS (
    SELECT p.supplier_id,
           (po.actual_delivery_date - po.order_date)              AS observed_lead_time,
           (po.actual_delivery_date <= po.expected_delivery_date) AS on_time
    FROM purchase_orders po
    JOIN products p USING (sku_id)
    WHERE po.status = 'received' AND po.actual_delivery_date IS NOT NULL
)
SELECT s.supplier_id, s.supplier_name,
       s.avg_lead_time_days                                     AS stated_avg_lead_time,
       s.lead_time_std_days                                     AS stated_lead_time_std,
       COUNT(r.observed_lead_time)                              AS received_orders,
       ROUND(AVG(r.observed_lead_time), 2)                      AS observed_avg_lead_time,
       ROUND(STDDEV_SAMP(r.observed_lead_time), 2)              AS observed_lead_time_std,
       ROUND(AVG(CASE WHEN r.on_time THEN 1.0 ELSE 0.0 END), 4) AS on_time_rate,
       ROUND(AVG(r.observed_lead_time) - s.avg_lead_time_days, 2) AS avg_gap_vs_stated_days
FROM suppliers s
LEFT JOIN received r USING (supplier_id)
GROUP BY s.supplier_id, s.supplier_name, s.avg_lead_time_days, s.lead_time_std_days
ORDER BY avg_gap_vs_stated_days DESC NULLS LAST;
