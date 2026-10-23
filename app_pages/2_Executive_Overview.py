"""Page 2 - Executive Overview: headline KPIs and distribution charts."""
import streamlit as st

from src.analytics.demand import sales_trend
from src.analytics.kpis import summary_by
from src.inventory.planning import ALERT_STATUSES
from src.ui import charts
from src.ui.components import (fmt_money, fmt_num, fmt_pct, formula_note, money_column,
                               page_header, share_column, units_column)
from src.ui.state import get_settings, require_result

page_header("Executive Overview", "Headline inventory health indicators calculated from the "
            "loaded dataset at the selected service level.")
dataset, result = require_result()
k, plan, settings = result.kpis, result.plan, get_settings()
cur = settings.currency_symbol
window = result.window

c1, c2, c3, c4 = st.columns(4)
c1.metric("On-hand inventory value", fmt_money(k["inventory_value"], cur),
          help="Sum of on-hand quantity x unit cost.")
c2.metric("SKUs analysed", fmt_num(k["sku_count"]))
c3.metric("Products requiring reorder", fmt_num(k["reorder_required"]),
          help=f"Stock position at or below the reorder point at {settings.service_level:.1%} "
               "service level.")
c4.metric("Below safety stock", fmt_num(k["below_safety_stock"]),
          help="Products with demand whose available stock (on-hand - reserved) is below "
               "their safety stock.")
c5, c6, c7, c8 = st.columns(4)
c5.metric("Est. annual holding cost", fmt_money(k["holding_cost"], cur),
          help=f"Inventory value x {settings.holding_cost_rate:.0%} holding-cost rate. Current "
               "value is used as the estimate of average inventory (one snapshot available).")
c6.metric("Turnover (per year)", fmt_num(k["turnover_annualised"], 2),
          help="COGS / average inventory value, scaled to 12 months.")
c7.metric("Days of inventory on hand", fmt_num(k["days_inventory_on_hand"], 0),
          help="Days in the period / period turnover.")
c8.metric("Excess inventory (estimate)", fmt_money(k["excess_value"], cur),
          help=f"Value of available stock above target level + {settings.excess_buffer_days} "
               "days of demand, plus all stock of items without demand.")

if window:
    period_note = (f"Period: {window.start:%Y-%m-%d} to {window.end:%Y-%m-%d} ({window.days} days)."
                   + ("" if window.is_full_year else " Less than a year of history - annual "
                      "figures are **annualised estimates**."))
    st.caption(period_note)
if k["insufficient_data"]:
    st.warning(f"{k['insufficient_data']:,} products have insufficient data (unknown supplier "
               "lead time or too little history) and are excluded from alert counts.")

st.divider()
left, right = st.columns(2)
with left:
    by_cat = summary_by(plan, "category")
    st.plotly_chart(charts.bar(by_cat, "category", "inventory_value", "Inventory value by category",
                               horizontal=True, labels={"inventory_value": f"Inventory value ({cur})",
                                                        "category": ""},
                               text_format="%{x:,.3s}"), width="stretch")
with right:
    counts = (plan["alert_status"].value_counts().reindex(ALERT_STATUSES).dropna()
              .rename("products").reset_index())
    st.plotly_chart(charts.status_bar(counts, "Products by stock status"), width="stretch")

left, right = st.columns(2)
with left:
    by_abc = summary_by(plan, "abc_class").sort_values("abc_class")
    st.plotly_chart(charts.bar(by_abc, "abc_class", "inventory_value", "Inventory value by ABC class",
                               color="abc_class", color_map=charts.CLASS_COLORS,
                               labels={"inventory_value": f"Inventory value ({cur})",
                                       "abc_class": "ABC class"}, text_format="%{y:,.3s}"),
                    width="stretch")
with right:
    trend = sales_trend(dataset.sales, dataset.products, "MS")
    if trend.empty:
        st.info("No sales history - demand trend not available.")
    else:
        st.plotly_chart(charts.line(trend, "period", "cogs", "Monthly cost of goods sold (units x unit cost)",
                                    labels={"cogs": f"COGS ({cur})", "period": ""}), width="stretch")
st.info("A stock-level trend needs several stock snapshots per SKU. This dataset has one "
        "snapshot per SKU, so stock trends are not shown; the sales trend is shown instead.",
        icon=":material/info:")

st.subheader("Category summary")
by_cat = summary_by(plan, "category")
st.dataframe(by_cat, hide_index=True, width="stretch", column_config={
    "inventory_value": money_column(cur), "excess_value": money_column(cur),
    "suggested_order_cost": money_column(cur), "on_hand_units": units_column(),
    "share_of_inventory_value": share_column()})

formula_note("How these KPIs are calculated", f"""
- **Inventory value** = on-hand quantity x unit cost.
- **Estimated annual holding cost** = average inventory value x holding-cost rate ({settings.holding_cost_rate:.0%}).
- **COGS (period)** = units sold in the analysis window x unit cost = {fmt_money(k['cogs_period'], cur)}.
- **Inventory turnover** = COGS / average inventory value. Period turnover {fmt_num(k['turnover_period'], 2)};
  annualised {fmt_num(k['turnover_annualised'], 2)}.
- **Days of inventory on hand** = days in period / period turnover.
- **Potential stock-out exposure** {fmt_money(k['stockout_exposure'], cur)} = expected lead-time demand not
  covered by the stock position x selling price. It is an estimate of revenue at risk if no action is
  taken, not a forecast of lost sales.
- Out of stock now (with demand): {fmt_num(k['out_of_stock'])} products. Share of SKUs requiring reorder:
  {fmt_pct(k['reorder_required'] / k['sku_count'] if k['sku_count'] else None)}.
""")
