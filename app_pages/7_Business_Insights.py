"""Page 7 - Business Insights & Reports: risks, excess, variability, suppliers, downloads."""
import streamlit as st

from src.analytics import suppliers as sup
from src.analytics.classification import NO_DEMAND
from src.config import SCENARIO_SERVICE_LEVELS
from src.inventory.planning import RISK_ELEVATED, RISK_HIGH, RISK_OUT
from src.inventory.scenarios import compare_scenarios, scenario_plans
from src.reporting.exports import (classification_report, cleaned_inventory_report,
                                   data_quality_report, replenishment_report, stockout_risk_report)
from src.ui.components import (download_button, empty_state, filter_bar, fmt_money, fmt_num,
                               fmt_pct, money_column, page_header, units_column)
from src.ui.state import get_prepared, get_settings, require_result

page_header("Business Insights & Reports", "Data-driven findings for the current dataset and "
            "filters, plus all downloadable reports.")
dataset, result = require_result()
settings = get_settings()
cur = settings.currency_symbol
plan = filter_bar(result.plan, "ins", fields=("category", "supplier", "abc", "xyz"))
if plan.empty:
    empty_state()
    st.stop()

RISKY = [RISK_OUT, RISK_HIGH, RISK_ELEVATED]
at_risk = plan[(plan["abc_class"] == "A") & plan["stockout_risk"].isin(RISKY)] \
    .sort_values("stockout_exposure_value", ascending=False)
excess = plan[plan["excess_qty"] > 0].sort_values("excess_value", ascending=False)
unstable = plan[plan["abc_xyz"].isin(["AZ", "BZ"])].sort_values("inventory_value", ascending=False)
dead = plan[(plan["xyz_class"] == NO_DEMAND) & (plan["on_hand_qty"] > 0)]
supplier_table = sup.supplier_lead_time_analysis(dataset.suppliers, dataset.products,
                                                 dataset.purchase_orders,
                                                 get_prepared(dataset, settings).lead_times)
supplier_table = supplier_table[supplier_table["supplier_id"].isin(set(plan["supplier_id"]))]
review = supplier_table[supplier_table["needs_review"]]
skus_affected = int(plan["supplier_id"].isin(set(review["supplier_id"])).sum())

# --- Recommendations built only from calculated values --------------------
st.header("Key findings")
total_value = plan["inventory_value"].sum()
findings = []
if len(at_risk):
    findings.append(f"**{len(at_risk):,} high-value (class A) products have a potential stock-out risk** "
                    f"({(at_risk['stockout_risk'] == RISK_OUT).sum():,} already out of stock). Revenue "
                    f"exposure over one lead time is estimated at {fmt_money(at_risk['stockout_exposure_value'].sum(), cur)}. "
                    f"Reviewing their suggested orders ({fmt_money(at_risk['estimated_order_cost'].sum(), cur)}) first gives "
                    "the largest protection per order.")
if len(excess):
    share = excess["excess_value"].sum() / total_value if total_value else None
    findings.append(f"**Excess stock worth {fmt_money(excess['excess_value'].sum(), cur)} "
                    f"({fmt_pct(share)} of inventory value) across {len(excess):,} products.** The top 10 "
                    f"items hold {fmt_money(excess['excess_value'].head(10).sum(), cur)}; consider pausing "
                    "orders, transfers or promotions for them.")
if len(dead):
    findings.append(f"**{len(dead):,} products had no sales in the period but still hold "
                    f"{fmt_money(dead['inventory_value'].sum(), cur)} of stock** - review for obsolescence.")
if len(unstable):
    findings.append(f"**{len(unstable):,} A/B products have erratic demand (AZ/BZ)**, holding "
                    f"{fmt_money(unstable['inventory_value'].sum(), cur)}. Formula safety stock is least reliable "
                    "here; review demand drivers with sales teams.")
if len(review):
    findings.append(f"**{len(review):,} suppliers need a lead-time review**, affecting {skus_affected:,} "
                    "products. Late or variable deliveries increase the safety stock needed.")
reorder = plan[plan["alert_status"] == "Reorder Required"]
if len(reorder):
    findings.append(f"**{len(reorder):,} products are at or below their reorder point** at "
                    f"{settings.service_level:.1%} service level; suggested replenishment totals "
                    f"{fmt_money(plan['estimated_order_cost'].sum(), cur)}.")
if not findings:
    st.success("No risks or excess found for the current filters.")
for item in findings:
    st.markdown(f"- {item}")
st.caption("All values are estimates under the model assumptions. No savings are claimed: "
           "verifying savings needs before-and-after data.")

tabs = st.tabs(["High-value at risk", "Excess inventory", "Unstable demand", "Supplier review",
                "Download reports"])
with tabs[0]:
    if at_risk.empty:
        empty_state("No class A products with potential stock-out risk.")
    else:
        st.dataframe(at_risk[["sku_id", "product_name", "category", "supplier_id", "stockout_risk",
                              "available_qty", "stock_position", "reorder_point", "days_of_cover",
                              "avg_lead_time_days", "potential_shortfall_units", "stockout_exposure_value",
                              "suggested_order_qty", "estimated_order_cost"]],
                     hide_index=True, width="stretch", column_config={
                         "stockout_exposure_value": money_column(cur),
                         "estimated_order_cost": money_column(cur),
                         "reorder_point": units_column(decimals=1),
                         "days_of_cover": units_column(), "potential_shortfall_units": units_column()})
        st.caption("Risk levels: *Out of stock now* = no available stock; *High* = stock position "
                   "below expected lead-time demand; *Elevated* = at or below the reorder point.")
with tabs[1]:
    if excess.empty:
        empty_state("No excess inventory.")
    else:
        st.dataframe(excess[["sku_id", "product_name", "category", "abc_class", "xyz_class",
                             "available_qty", "excess_qty", "excess_value", "days_of_cover",
                             "status_reason"]].head(500), hide_index=True, width="stretch",
                     column_config={"excess_value": money_column(cur), "excess_qty": units_column(),
                                    "days_of_cover": units_column()})
with tabs[2]:
    if unstable.empty:
        empty_state("No AZ/BZ products.")
    else:
        st.dataframe(unstable[["sku_id", "product_name", "category", "abc_xyz", "cv",
                               "avg_daily_demand", "std_daily_demand", "inventory_value",
                               "safety_stock", "alert_status"]], hide_index=True, width="stretch",
                     column_config={"cv": st.column_config.NumberColumn(format="%.2f"),
                                    "inventory_value": money_column(cur),
                                    "avg_daily_demand": units_column(decimals=2),
                                    "std_daily_demand": units_column(decimals=2),
                                    "safety_stock": units_column(decimals=1)})
with tabs[3]:
    st.caption(f"Review rules: observed lead time > {sup.LATE_FACTOR:.0%} of stated, on-time rate < "
               f"{sup.MIN_ON_TIME_RATE:.0%}, lead-time CV > {sup.MAX_LT_CV}, or no variability data. "
               "Observed values come from received purchase orders.")
    if not dataset.has_purchase_orders:
        st.info("No purchase-order file: observed lead times and on-time rates cannot be calculated.")
    st.dataframe(supplier_table, hide_index=True, width="stretch", column_config={
        "on_time_rate": st.column_config.NumberColumn(format="percent"),
        "observed_avg_lead_time": st.column_config.NumberColumn(format="%.1f"),
        "observed_lead_time_std": st.column_config.NumberColumn(format="%.1f"),
        "lead_time_std_used": st.column_config.NumberColumn(format="%.1f"),
        "avg_delay_days": st.column_config.NumberColumn(format="%.1f")})
with tabs[4]:
    st.caption("Every report reflects the current dataset and the filters at the top of this page.")
    prepared = get_prepared(dataset, settings)
    plans = scenario_plans(prepared.classified, prepared.lead_times, prepared.incoming, settings,
                           SCENARIO_SERVICE_LEVELS)
    plans = {sl: p[p["sku_id"].isin(set(plan["sku_id"]))] for sl, p in plans.items()}
    reports = [
        (cleaned_inventory_report(plan), "cleaned_inventory", "Cleaned inventory data"),
        (classification_report(plan), "abc_xyz_classification", "ABC/XYZ classification"),
        (replenishment_report(plan[plan["suggested_order_qty"] > 0]), "replenishment_recommendations",
         "Reorder recommendations"),
        (stockout_risk_report(plan), "stockout_risk", "Stock-out risk report"),
        (compare_scenarios(plans, settings), "scenario_comparison", "Scenario comparison (90/95/99%)"),
        (supplier_table, "supplier_lead_time_review", "Supplier lead-time review"),
        (data_quality_report(dataset.validation), "data_quality_report", "Data-quality report"),
    ]
    cols = st.columns(2)
    for i, (frame, name, label) in enumerate(reports):
        with cols[i % 2]:
            download_button(frame, name, f"{label} ({fmt_num(len(frame))} rows)", dataset, f"dl_r{i}")
