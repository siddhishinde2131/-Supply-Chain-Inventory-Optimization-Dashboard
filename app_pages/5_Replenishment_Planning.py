"""Page 5 - Replenishment Planning: reorder alerts and suggested order quantities."""
import plotly.graph_objects as go
import streamlit as st

from src.inventory.planning import (ALERT_STATUSES, STATUS_INSUFFICIENT, STATUS_LOW,
                                    STATUS_REORDER, lead_time_model_counts)
from src.reporting.exports import replenishment_report
from src.ui import charts
from src.ui.components import (download_button, empty_state, filter_bar, fmt_money, fmt_num,
                               formula_note, money_column, page_header, units_column)
from src.ui.state import get_settings, require_result

page_header("Replenishment Planning", "Recommendations for a planner to review. No purchase "
            "order is created automatically.")
dataset, result = require_result()
settings = get_settings()
cur = settings.currency_symbol
plan = result.plan
st.caption(f"Service level **{settings.service_level:.1%}** (Z = {plan['z_score'].iloc[0]:.3f}) - change "
           "it in the sidebar. Policy: when stock position <= reorder point, order up to reorder "
           f"point + {settings.target_coverage_days} days of demand, respecting MOQ and order multiples.")

filtered = filter_bar(plan, "rep")
needs_order = filtered[filtered["suggested_order_qty"] > 0]

c1, c2, c3, c4 = st.columns(4)
c1.metric("Reorder Required", fmt_num((filtered["alert_status"] == STATUS_REORDER).sum()))
c2.metric("Low Stock (incoming orders pending)", fmt_num((filtered["alert_status"] == STATUS_LOW).sum()))
c3.metric("Suggested order lines", fmt_num(len(needs_order)))
c4.metric("Estimated purchase cost", fmt_money(needs_order["estimated_order_cost"].sum(), cur),
          help="Suggested quantity x unit cost. Excludes freight, discounts and taxes.")

only_orders = st.toggle("Show only products with a suggested order", value=True, key="rep_only")
view = needs_order if only_orders else filtered
if view.empty:
    empty_state("No products need ordering for the current filters." if only_orders else
                "No records match the selected filters.")
else:
    cols = ["sku_id", "product_name", "category", "supplier_id", "abc_class", "xyz_class",
            "on_hand_qty", "reserved_qty", "incoming_qty", "stock_position", "avg_daily_demand",
            "avg_lead_time_days", "safety_stock", "reorder_point", "target_stock_level",
            "suggested_order_qty", "min_order_qty", "order_multiple", "unit_cost",
            "estimated_order_cost", "alert_status", "stockout_risk", "ss_model"]
    st.dataframe(view[cols].sort_values("estimated_order_cost", ascending=False), hide_index=True,
                 width="stretch", height=460, column_config={
                     "avg_daily_demand": units_column(decimals=2),
                     "safety_stock": units_column(decimals=1), "reorder_point": units_column(decimals=1),
                     "target_stock_level": units_column(decimals=1),
                     "suggested_order_qty": units_column(), "unit_cost": money_column(cur),
                     "estimated_order_cost": money_column(cur)})
download_button(replenishment_report(view), "replenishment_recommendations",
                "Download replenishment recommendations (filtered)", dataset, "dl_rep",
                suffix=f"sl{settings.service_level * 100:g}")

st.divider()
left, right = st.columns(2)
with left:
    by_supplier = (needs_order.groupby(["supplier_id", "supplier_name"], dropna=False)
                   .agg(order_lines=("sku_id", "count"), estimated_cost=("estimated_order_cost", "sum"))
                   .reset_index().sort_values("estimated_cost", ascending=False).head(15))
    if by_supplier.empty:
        st.info("No suggested orders to group by supplier.")
    else:
        st.plotly_chart(charts.bar(by_supplier, "supplier_id", "estimated_cost",
                                   "Estimated purchase cost by supplier (top 15)", horizontal=True,
                                   labels={"estimated_cost": f"Cost ({cur})", "supplier_id": ""},
                                   text_format="%{x:,.3s}"), width="stretch")
with right:
    status = (filtered["alert_status"].value_counts().reindex(ALERT_STATUSES).dropna()
              .rename("products").reset_index())
    st.plotly_chart(charts.status_bar(status, "Alert status (filtered products)"), width="stretch")

st.subheader("Stock position vs safety stock and reorder point")
top = needs_order.nlargest(20, "estimated_order_cost")
if top.empty:
    st.info("No products to compare.")
else:
    fig = go.Figure()
    for name, col, color in (("Safety stock", "safety_stock", charts.CATEGORICAL[2]),
                             ("Reorder point", "reorder_point", charts.CATEGORICAL[1]),
                             ("Stock position", "stock_position", charts.CATEGORICAL[0])):
        fig.add_bar(x=top["sku_id"], y=top[col], name=name, marker_color=color,
                    hovertemplate="%{x}<br>" + name + ": %{y:,.0f} units<extra></extra>")
    fig.update_layout(barmode="group", title="Top 20 suggested orders by cost", yaxis_title="Units")
    st.plotly_chart(charts.style(fig, 420), width="stretch")

with st.expander("Safety-stock model and lead-time source per product"):
    st.dataframe(lead_time_model_counts(plan), hide_index=True)
    insufficient = plan[plan["alert_status"] == STATUS_INSUFFICIENT]
    if len(insufficient):
        st.warning(f"{len(insufficient):,} products have insufficient data and no recommendation.")
        st.dataframe(insufficient[["sku_id", "product_name", "supplier_id", "status_reason"]],
                     hide_index=True)

formula_note("Formulas and assumptions", f"""
- **Stock position** = on-hand - reserved + open and in-transit purchase orders (cancelled, received
  or already-delivered orders never count).
- **Safety stock** = Z x sqrt(L x sigma_d^2 + d^2 x sigma_L^2) when lead-time variability is known; otherwise
  the fixed-lead-time model Z x sigma_d x sqrt(L). d = average daily demand, sigma_d = sample standard deviation of
  daily demand, L = average lead time (days), sigma_L = lead-time standard deviation.
- **Reorder point** = d x L + safety stock.
- **Suggested quantity** = target level - stock position (if stock position <= ROP), raised to the MOQ and
  rounded up to the order multiple. Target level = ROP + {settings.target_coverage_days} x d.
- Assumes demand and lead time are independent and lead-time demand is roughly normal. Alerts are
  **potential** risks under these assumptions, not certainties.
""")
