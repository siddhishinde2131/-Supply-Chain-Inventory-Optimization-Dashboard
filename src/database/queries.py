"""Catalogue of the SQL analytics in sql/analytics with their parameters."""
from dataclasses import dataclass


@dataclass(frozen=True)
class QueryInfo:
    name: str            # file name without .sql
    title: str
    description: str
    params: tuple[str, ...] = ()


QUERIES = (
    QueryInfo("inventory_value_by_category", "Inventory value by category",
              "Units and value per category from the latest snapshot (CTE + window total)."),
    QueryInfo("top_value_products", "Highest-value products",
              "Ranks products by stock value with the running share of total value.",
              ("limit",)),
    QueryInfo("sales_by_sku_date", "Sales by SKU and date",
              "Daily sales of one SKU with zero-filled days and a 7-day moving average.",
              ("sku_id", "start_date", "end_date")),
    QueryInfo("demand_summary", "Product demand summary",
              "Average and standard deviation of daily demand per SKU in the window.",
              ("start_date", "end_date")),
    QueryInfo("supplier_lead_time_analysis", "Supplier lead-time analysis",
              "Stated vs observed lead time, variability and on-time rate per supplier."),
    QueryInfo("products_below_reorder_point", "Products below reorder point",
              "Uses the Python-calculated metrics stored in inventory_metrics.", ("limit",)),
    QueryInfo("abc_support", "ABC classification support",
              "Consumption value and cumulative share with window functions.",
              ("start_date", "end_date", "annual_factor", "a_threshold", "b_threshold")),
    QueryInfo("inventory_rankings", "Inventory rankings (window functions)",
              "RANK, DENSE_RANK, PERCENT_RANK and NTILE by inventory value.",
              ("max_rank_in_category",)),
    QueryInfo("inventory_health_cte", "Inventory health (CTE analysis)",
              "Chained CTEs: stock, demand, incoming orders and days-of-cover buckets.",
              ("start_date", "end_date")),
)
QUERY_BY_NAME = {q.name: q for q in QUERIES}
