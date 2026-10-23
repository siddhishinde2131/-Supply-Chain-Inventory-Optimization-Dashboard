"""Page 4 - ABC/XYZ Analysis: value and variability classification."""
import streamlit as st

from src.analytics.classification import (ABC_MEANING, GROUP_RECOMMENDATIONS, XYZ_MEANING,
                                          abc_summary, abc_xyz_matrix, xyz_summary)
from src.reporting.exports import classification_report
from src.ui import charts
from src.ui.components import (download_button, empty_state, filter_bar, formula_note,
                               money_column, page_header, share_column, units_column)
from src.ui.state import get_settings, require_result

page_header("ABC/XYZ Analysis", "ABC ranks products by annual consumption value; XYZ by how "
            "predictable their daily demand is. Together they tell you where to focus.")
dataset, result = require_result()
settings = get_settings()
cur = settings.currency_symbol
plan, window = result.plan, result.window

if window is None:
    st.warning("No sales history: ABC/XYZ classification is not possible.")
    st.stop()
basis = ("full-year observed values" if window.is_full_year else
         f"**annualised estimates** from {window.days} observed days (x {window.annualisation_factor:.2f})")
st.caption(f"Analysis period {window.start:%Y-%m-%d} to {window.end:%Y-%m-%d}. Annual consumption "
           f"value uses {basis}. Thresholds: A < {settings.abc_a_threshold:.0%}, "
           f"B < {settings.abc_b_threshold:.0%} cumulative value; X: CV <= {settings.xyz_x_threshold}, "
           f"Y: CV <= {settings.xyz_y_threshold}, Z above. Change them on the Home page.")

tab_abc, tab_xyz, tab_matrix, tab_table = st.tabs(
    ["ABC (value)", "XYZ (variability)", "ABC/XYZ matrix", "Product classification"])

with tab_abc:
    summary = abc_summary(plan)
    st.dataframe(summary, hide_index=True, width="stretch", column_config={
        "annual_consumption_value": money_column(cur), "inventory_value": money_column(cur),
        "share_of_products": share_column(), "share_of_consumption_value": share_column(),
        "share_of_inventory_value": share_column()})
    left, right = st.columns([3, 2])
    left.plotly_chart(charts.pareto_curve(plan, settings.abc_a_threshold, settings.abc_b_threshold),
                      width="stretch")
    long = summary.melt(id_vars="abc_class", value_vars=["share_of_products",
                                                          "share_of_consumption_value"],
                        var_name="measure", value_name="share")
    long["measure"] = long["measure"].map({"share_of_products": "Share of SKUs",
                                           "share_of_consumption_value": "Share of value"})
    fig = charts.bar(long, "abc_class", "share", "SKUs vs value by class", color="measure",
                     labels={"share": "", "abc_class": "ABC class"}, text_format="%{y:.0%}")
    fig.update_layout(barmode="group")
    fig.update_yaxes(tickformat=".0%")
    right.plotly_chart(fig, width="stretch")
    zero = int((plan["abc_note"] != "").sum())
    if zero:
        st.caption(f"{zero:,} products had no consumption in the period and are placed in class C.")
    for cls, text in ABC_MEANING.items():
        st.markdown(f"**{cls}** - {text}")

with tab_xyz:
    xs = xyz_summary(plan)
    left, right = st.columns([2, 3])
    left.dataframe(xs, hide_index=True, width="stretch", column_config={
        "inventory_value": money_column(cur), "share_of_products": share_column(),
        "median_cv": st.column_config.NumberColumn(format="%.2f")})
    right.plotly_chart(charts.bar(xs, "xyz_class", "products", "Products by XYZ class",
                                  labels={"products": "Products", "xyz_class": ""},
                                  text_format="%{y:,}"), width="stretch")
    cv = plan["cv"].dropna()
    fig = charts.histogram(cv.clip(upper=5), "Demand variability (CV, capped at 5)", "CV")
    for level in (settings.xyz_x_threshold, settings.xyz_y_threshold):
        fig.add_vline(x=level, line_dash="dot", line_color=charts.NEUTRAL)
    st.plotly_chart(fig, width="stretch")
    for cls, text in XYZ_MEANING.items():
        st.markdown(f"**{cls}** - {text}")
    policy = ("days without a sales record count as **zero demand**" if settings.missing_days_as_zero
              else "only days **with a sales record** are used (zero-fill disabled)")
    st.caption(f"Policy: {policy}. Variance is the sample variance (n-1). Products with zero "
               "average demand are labelled 'No Demand' because CV is undefined.")

with tab_matrix:
    measure = st.radio("Show", ["Product count", "Inventory value"], horizontal=True, key="mx_measure")
    matrix = abc_xyz_matrix(plan, "products" if measure == "Product count" else "inventory_value")
    st.plotly_chart(charts.matrix_heatmap(matrix, f"ABC/XYZ matrix - {measure.lower()}",
                                          ",.0f" if measure == "Product count" else ",.3s"),
                    width="stretch")
    groups = plan[plan["abc_xyz"].isin(GROUP_RECOMMENDATIONS)]
    table = (groups.groupby("abc_xyz")
             .agg(products=("sku_id", "count"), inventory_value=("inventory_value", "sum"),
                  median_cv=("cv", "median"), reorder_required=("alert_status",
                                                                lambda s: int((s == "Reorder Required").sum())))
             .reindex(list(GROUP_RECOMMENDATIONS)).dropna(how="all").reset_index())
    table["focus"] = table["abc_xyz"].map(lambda g: GROUP_RECOMMENDATIONS[g][0])
    table["recommendation"] = table["abc_xyz"].map(lambda g: GROUP_RECOMMENDATIONS[g][1])
    st.dataframe(table, hide_index=True, width="stretch", column_config={
        "inventory_value": money_column(cur), "median_cv": st.column_config.NumberColumn(format="%.2f"),
        "recommendation": st.column_config.TextColumn(width="large")})
    other = plan[~plan["abc_xyz"].isin(GROUP_RECOMMENDATIONS)]
    if len(other):
        st.caption(f"{len(other):,} products are outside the 3x3 matrix (No Demand or Insufficient "
                   "Data) - see the product table.")
    st.markdown(f"""
**Reading the matrix**
- **Predictable demand:** AX, BX, CX ({int(plan['abc_xyz'].isin(['AX','BX','CX']).sum()):,} products) -
  automate replenishment with lean safety stock.
- **Closer monitoring:** AY, BY ({int(plan['abc_xyz'].isin(['AY','BY']).sum()):,} products) -
  valuable but variable; review regularly.
- **Further review:** AZ, BZ, CZ ({int(plan['abc_xyz'].isin(['AZ','BZ','CZ']).sum()):,} products) -
  erratic demand where formula-based stock may be unreliable.
""")

with tab_table:
    filtered = filter_bar(plan, "abc", fields=("search", "category", "supplier", "abc", "xyz"))
    if filtered.empty:
        empty_state()
    else:
        report = classification_report(filtered)
        st.dataframe(report, hide_index=True, width="stretch", height=480, column_config={
            "annual_consumption_value": money_column(cur),
            "observed_consumption_value": money_column(cur),
            "inventory_value": money_column(cur), "unit_cost": money_column(cur),
            "value_share": st.column_config.NumberColumn(format="%.4f"),
            "cumulative_share": st.column_config.NumberColumn(format="percent"),
            "cv": st.column_config.NumberColumn(format="%.2f"),
            "avg_daily_demand": units_column(decimals=2), "std_daily_demand": units_column(decimals=2),
            "annual_demand_estimate": units_column()})
        download_button(report, "abc_xyz_classification", "Download ABC/XYZ classification",
                        dataset, "dl_abc")

formula_note("ABC/XYZ formulas", """
- **Annual consumption value** = annual demand quantity x unit cost (annualised when history < 1 year).
- Products are ranked by value; **cumulative share before a product** decides its class
  (A while < A threshold, B while < B threshold, else C). Zero-value products are always C.
- **CV** = standard deviation of daily demand / mean daily demand.
""")
