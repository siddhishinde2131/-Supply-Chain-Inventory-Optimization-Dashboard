"""Page 6 - Scenario Analysis: compare service levels and what-if assumptions."""
import streamlit as st

from src.config import SCENARIO_SERVICE_LEVELS
from src.inventory.formulas import z_score
from src.inventory.scenarios import compare_scenarios, scenario_plans, sku_scenario_table
from src.ui import charts
from src.ui.components import (download_button, empty_state, filter_bar, fmt_level, fmt_money, fmt_num,
                               money_column, page_header, units_column)
from src.ui.state import get_prepared, get_settings, require_result

page_header("Scenario Analysis", "How much extra inventory investment does a higher service "
            "level need? All scenarios use exactly the same products, demand and lead times.")
dataset, result = require_result()
settings = get_settings()
cur = settings.currency_symbol

LEVEL_OPTIONS = [0.85, 0.90, 0.95, 0.975, 0.99, 0.995]
DEFAULTS = {"scn_levels": list(SCENARIO_SERVICE_LEVELS), "scn_holding": settings.holding_cost_rate * 100,
            "scn_demand": 0, "scn_lead": 0}


def reset_scenarios():
    for key, value in DEFAULTS.items():
        st.session_state[key] = value


for key, value in DEFAULTS.items():
    st.session_state.setdefault(key, value)

with st.container(border=True):
    c1, c2, c3, c4 = st.columns([3, 2, 2, 2])
    levels = c1.multiselect("Service levels to compare", LEVEL_OPTIONS, key="scn_levels",
                            format_func=fmt_level)
    holding = c2.number_input("Holding-cost rate (% per year)", 0.0, 100.0, step=1.0, key="scn_holding")
    demand_change = c3.slider("Demand change (%)", -50, 100, step=5, key="scn_demand",
                              help="What-if: scale average demand and its variability.")
    lead_change = c4.slider("Lead-time change (%)", -50, 100, step=5, key="scn_lead",
                            help="What-if: scale supplier lead times and their variability.")
    st.button("Reset scenario settings", on_click=reset_scenarios, icon=":material/restart_alt:")

if not levels:
    st.info("Select at least one service level.")
    st.stop()

prepared = get_prepared(dataset, settings)
with st.spinner("Calculating scenarios..."):
    plans = scenario_plans(prepared.classified, prepared.lead_times, prepared.incoming, settings,
                           sorted(levels), 1 + demand_change / 100, 1 + lead_change / 100)
comparison = compare_scenarios(plans, settings, holding / 100)
if demand_change or lead_change:
    st.warning(f"What-if active: demand {demand_change:+d}%, lead time {lead_change:+d}%. Results "
               "are hypothetical.", icon=":material/science:")

base, top = comparison.iloc[0], comparison.iloc[-1]
c1, c2, c3 = st.columns(3)
c1.metric(f"Safety stock value at {fmt_level(top['service_level'])}", fmt_money(top["safety_stock_value"], cur),
          delta=fmt_money(top["additional_safety_stock_investment"], cur) + f" vs {fmt_level(base['service_level'])}",
          delta_color="off")
c2.metric(f"Est. annual holding cost at {fmt_level(top['service_level'])}",
          fmt_money(top["estimated_annual_holding_cost"], cur),
          delta=fmt_money(top["additional_annual_holding_cost"], cur) + f" vs {fmt_level(base['service_level'])}",
          delta_color="off")
c3.metric(f"Products to reorder at {fmt_level(top['service_level'])}", fmt_num(top["reorder_required"]),
          delta=f"{int(top['reorder_required'] - base['reorder_required']):+,} vs {fmt_level(base['service_level'])}",
          delta_color="off")

st.subheader("Comparison table")
st.dataframe(comparison, hide_index=True, width="stretch", column_config={
    "service_level": st.column_config.NumberColumn(format="percent"),
    "z_score": st.column_config.NumberColumn(format="%.3f"),
    "safety_stock_units": units_column(), "suggested_order_units": units_column(),
    **{c: money_column(cur) for c in ("safety_stock_value", "suggested_order_cost",
                                      "estimated_avg_inventory_value", "estimated_annual_holding_cost",
                                      "safety_stock_holding_cost", "additional_safety_stock_investment",
                                      "additional_annual_holding_cost")}})
download_button(comparison, "scenario_comparison", "Download scenario comparison", dataset, "dl_scn")

chart_df = comparison.assign(level=comparison["service_level"].map(fmt_level))
c1, c2, c3 = st.columns(3)
c1.plotly_chart(charts.bar(chart_df, "level", "safety_stock_value", "Safety stock investment",
                           labels={"safety_stock_value": f"Value ({cur})", "level": "Service level"},
                           text_format="%{y:,.3s}", height=340), width="stretch")
c2.plotly_chart(charts.bar(chart_df, "level", "estimated_annual_holding_cost",
                           "Estimated annual holding cost",
                           labels={"estimated_annual_holding_cost": f"Cost ({cur})",
                                   "level": "Service level"}, text_format="%{y:,.3s}", height=340),
                width="stretch")
c3.plotly_chart(charts.bar(chart_df, "level", "reorder_required", "Products requiring reorder",
                           labels={"reorder_required": "Products", "level": "Service level"},
                           text_format="%{y:,}", height=340), width="stretch")

st.subheader("Product-level comparison")
table = sku_scenario_table(plans)
first_plan = next(iter(plans.values()))
filtered_ids = set(filter_bar(first_plan, "scn", fields=("search", "category", "abc", "xyz"))["sku_id"])
table = table[table["sku_id"].isin(filtered_ids)]
if table.empty:
    empty_state()
else:
    st.dataframe(table, hide_index=True, width="stretch", height=400)
    download_button(table, "scenario_sku_comparison", "Download product-level scenario table",
                    dataset, "dl_scn_sku")

st.subheader("How to read this")
zs = ", ".join(f"{fmt_level(sl)} -> Z = {z_score(sl):.3f}" for sl in sorted(levels))
st.markdown(f"""
- The **service level** is the target probability of *not* running out during a replenishment cycle.
  Z-scores used: {zs}.
- Safety stock grows with Z, and Z grows **faster** as you approach 100%: going from 95% to 99% costs much
  more than 90% to 95%. This is the trade-off between availability and working capital.
- **Estimated average inventory** = safety stock + half of a typical order ({settings.target_coverage_days}
  days of demand). **Holding cost** = that value x the holding-cost rate. Both are planning estimates.
- Even at 99% the model does not guarantee zero stock-outs: it assumes normal, independent demand and
  lead times, and real disruptions (supplier failures, demand shocks) fall outside these assumptions.
- The additional working capital of each scenario is its safety-stock value minus that of the lowest
  selected service level.
""")
