"""Page 3 - Inventory Analysis: product table, stock levels, demand trends, excess, SQL."""
import pandas as pd
import streamlit as st

from src.analytics.demand import category_growth, monthly_seasonality, sales_trend, weekday_seasonality
from src.analytics.kpis import summary_by
from src.config import SQL_DIR
from src.database import repository as repo
from src.database.connection import DatabaseError, connection
from src.database.queries import QUERIES, QUERY_BY_NAME
from src.reporting.exports import cleaned_inventory_report
from src.ui import charts
from src.ui.components import (download_button, empty_state, fmt_money, filter_bar, formula_note,
                               money_column, page_header, units_column)
from src.ui.state import get_settings, require_result

page_header("Inventory Analysis", "Explore products, stock levels, demand trends and excess "
            "stock. Filters apply to every tab.")
dataset, result = require_result()
settings = get_settings()
cur = settings.currency_symbol
plan = result.plan

filtered = filter_bar(plan, "inv")
tabs = st.tabs(["Products", "Stock levels", "Sales & demand trends", "Excess inventory",
                "Inventory aging", "SQL analytics"])

with tabs[0]:
    if filtered.empty:
        empty_state()
    else:
        cols = ["sku_id", "product_name", "category", "supplier_id", "abc_class", "xyz_class",
                "on_hand_qty", "reserved_qty", "available_qty", "incoming_qty", "stock_position",
                "unit_cost", "inventory_value", "avg_daily_demand", "days_of_cover", "alert_status"]
        st.dataframe(filtered[cols].sort_values("inventory_value", ascending=False),
                     hide_index=True, width="stretch", height=480, column_config={
                         "inventory_value": money_column(cur), "unit_cost": money_column(cur),
                         "avg_daily_demand": units_column(decimals=2),
                         "days_of_cover": units_column(decimals=0)})
        download_button(cleaned_inventory_report(filtered), "cleaned_inventory",
                        "Download cleaned inventory data (filtered)", dataset, "dl_inv")

with tabs[1]:
    if filtered.empty:
        empty_state()
    else:
        left, right = st.columns(2)
        by_cat = summary_by(filtered, "category")
        left.plotly_chart(charts.bar(by_cat, "category", "inventory_value",
                                     "Inventory value by category", horizontal=True,
                                     labels={"inventory_value": f"Value ({cur})", "category": ""},
                                     text_format="%{x:,.3s}"), width="stretch")
        cover = filtered["days_of_cover"].clip(upper=365)
        right.plotly_chart(charts.histogram(cover, "Days of cover (available stock / daily demand)",
                                            "Days of cover (capped at 365)"), width="stretch")
        st.caption(f"{filtered['days_of_cover'].isna().sum():,} products without demand have no "
                   "days-of-cover value and are not in the histogram.")

with tabs[2]:
    period = dataset.sales_period
    if period is None:
        st.info("No sales history in this dataset.")
    else:
        c1, c2 = st.columns([2, 1])
        dates = c1.date_input("Date range", (period[0].date(), period[1].date()),
                              min_value=period[0].date(), max_value=period[1].date(), key="inv_dates")
        freq = c2.radio("Granularity", ["Weekly", "Monthly"], horizontal=True, key="inv_freq")
        if not isinstance(dates, tuple) or len(dates) != 2:
            st.info("Select a start and an end date.")
        else:
            sku_set = set(filtered["sku_id"])
            sales = dataset.sales[dataset.sales["sku_id"].isin(sku_set)
                                  & dataset.sales["sale_date"].between(pd.Timestamp(dates[0]),
                                                                       pd.Timestamp(dates[1]))]
            if sales.empty:
                empty_state("No sales for the selected products and dates.")
            else:
                trend = sales_trend(sales, dataset.products, "W-MON" if freq == "Weekly" else "MS",
                                    by="category")
                st.plotly_chart(charts.line(trend, "period", "units", f"{freq} units sold by category",
                                            color="category", labels={"units": "Units", "period": ""}),
                                width="stretch")
                st.caption("Partial first/last periods can look lower because they contain fewer days.")
        win = result.window
        left, right = st.columns(2)
        weekday = weekday_seasonality(dataset.sales[dataset.sales["sku_id"].isin(set(filtered["sku_id"]))], win)
        if weekday is None:
            left.info("Weekday pattern needs at least 8 weeks of history.")
        else:
            left.plotly_chart(charts.bar(weekday, "weekday", "index_vs_average",
                                         "Weekday demand index (1.0 = average day)",
                                         labels={"index_vs_average": "Index", "weekday": ""},
                                         text_format="%{y:.2f}"), width="stretch")
        monthly = monthly_seasonality(dataset.sales[dataset.sales["sku_id"].isin(set(filtered["sku_id"]))], win)
        if monthly is None:
            right.info("Month-of-year seasonality needs at least 12 months of history.")
        else:
            right.plotly_chart(charts.bar(monthly, "month", "index_vs_average",
                                          "Month-of-year demand index (1.0 = average)",
                                          labels={"index_vs_average": "Index", "month": "Month"},
                                          text_format="%{y:.2f}"), width="stretch")
        growth = category_growth(dataset.sales, dataset.products, win)
        if growth is not None:
            st.markdown("**Demand trend by category - last 90 days vs previous 90 days**")
            st.dataframe(growth, hide_index=True, width="stretch", column_config={
                "change_pct": st.column_config.NumberColumn("change", format="percent"),
                "prior_units": units_column(), "recent_units": units_column()})

with tabs[3]:
    excess = filtered[filtered["excess_qty"] > 0].sort_values("excess_value", ascending=False)
    st.metric("Excess inventory value (filtered)", fmt_money(excess["excess_value"].sum(), cur))
    if excess.empty:
        empty_state("No excess stock for the current filters.")
    else:
        by_cat = summary_by(excess, "category")
        st.plotly_chart(charts.bar(by_cat, "category", "excess_value", "Excess value by category",
                                   horizontal=True, labels={"excess_value": f"Excess ({cur})",
                                                            "category": ""},
                                   text_format="%{x:,.3s}"), width="stretch")
        st.dataframe(excess[["sku_id", "product_name", "category", "abc_class", "xyz_class",
                             "available_qty", "target_stock_level", "excess_qty", "excess_value",
                             "avg_daily_demand", "days_of_cover", "status_reason"]],
                     hide_index=True, width="stretch", column_config={
                         "excess_value": money_column(cur), "target_stock_level": units_column(),
                         "excess_qty": units_column(), "avg_daily_demand": units_column(decimals=2),
                         "days_of_cover": units_column()})
    formula_note("Excess inventory rule", f"""
Excess units = available stock - (target stock level + {settings.excess_buffer_days} days of average demand),
never below zero. Target stock level = reorder point + {settings.target_coverage_days} days of demand.
Products with **no demand in the period** count all available stock as excess. This flags stock for
**review** (markdown, transfer, return); it is not proof that the stock is unsellable.""")

with tabs[4]:
    st.info("Inventory aging is **not calculated**: it requires receipt dates per stock lot "
            "(when each unit arrived), which the supported input files do not contain. Showing "
            "an age without that data would be a fabricated result.", icon=":material/info:")

with tabs[5]:
    if dataset.source_type != "postgresql":
        st.info("SQL analytics run on the PostgreSQL tables. Switch to **PostgreSQL mode** on the "
                "Home page, store a dataset and choose *Analyse data stored in PostgreSQL*. "
                "The SQL files are in the `sql/analytics` folder.", icon=":material/storage:")
    elif not st.session_state.get("db_ok"):
        st.warning("The database connection is not active. Test the connection on the Home page.")
    else:
        cfg = st.session_state["db_config"]
        win = result.window
        query = st.selectbox("Query", [q.name for q in QUERIES],
                             format_func=lambda n: QUERY_BY_NAME[n].title, key="sql_query")
        info = QUERY_BY_NAME[query]
        st.caption(info.description)
        params = {}
        pcols = st.columns(max(1, len(info.params)))
        for col, name in zip(pcols, info.params):
            if name == "limit":
                params[name] = col.number_input("Rows", 1, 5000, 25, key="sql_limit")
            elif name == "max_rank_in_category":
                params[name] = col.number_input("Top N per category", 1, 100, 5, key="sql_rank")
            elif name == "sku_id":
                params[name] = col.selectbox("SKU", plan["sku_id"].tolist(), key="sql_sku")
            elif name == "start_date":
                params[name] = col.date_input("Start", win.start.date(), key="sql_start")
            elif name == "end_date":
                params[name] = col.date_input("End", win.end.date(), key="sql_end")
            elif name == "annual_factor":
                params[name] = win.annualisation_factor
                col.metric("Annualisation factor", f"{win.annualisation_factor:.3f}")
            elif name == "a_threshold":
                params[name] = settings.abc_a_threshold
                col.metric("A threshold", f"{settings.abc_a_threshold:.0%}")
            elif name == "b_threshold":
                params[name] = settings.abc_b_threshold
                col.metric("B threshold", f"{settings.abc_b_threshold:.0%}")
        if query == "products_below_reorder_point":
            if st.button(f"Store current metrics in PostgreSQL ({settings.service_level:.1%} service level)",
                         icon=":material/save:"):
                try:
                    with connection(cfg) as conn:
                        n = repo.save_inventory_metrics(conn, plan)
                    st.success(f"Stored metrics for {n:,} products in inventory_metrics.")
                except DatabaseError as exc:
                    st.error(str(exc))
        with st.expander("Show SQL"):
            st.code((SQL_DIR / "analytics" / f"{query}.sql").read_text(encoding="utf-8"), "sql")
        if st.button("Run query", type="primary", icon=":material/play_arrow:"):
            try:
                with st.spinner("Running SQL..."), connection(cfg) as conn:
                    st.session_state["sql_result"] = (query, repo.run_query(conn, query, params))
            except DatabaseError as exc:
                st.error(str(exc))
        stored = st.session_state.get("sql_result")
        if stored and stored[0] == query:
            df = stored[1]
            if df.empty:
                st.info("The query returned no rows."
                        + (" Store the current metrics first." if query == "products_below_reorder_point" else ""))
            else:
                st.dataframe(df, hide_index=True, width="stretch")
                download_button(df, f"sql_{query}", "Download query result", dataset, "dl_sql")
                # Reconciliation: SQL and Python must agree (formulas are centralised)
                if query == "inventory_value_by_category":
                    py = plan.groupby("category")["inventory_value"].sum()
                    diff = (df.set_index("category")["inventory_value"] - py).abs().max()
                    st.success(f"Reconciliation with Python: max difference {fmt_money(diff, cur, 2)}.")
                elif query == "abc_support" and params["start_date"] == win.start.date() \
                        and params["end_date"] == win.end.date():
                    merged = df.merge(plan[["sku_id", "abc_class"]], on="sku_id", suffixes=("_sql", "_py"))
                    agree = (merged["abc_class_sql"] == merged["abc_class_py"]).mean()
                    st.success(f"Reconciliation: SQL and Python ABC classes agree for {agree:.2%} of SKUs.")
                elif query == "demand_summary" and settings.missing_days_as_zero \
                        and params["start_date"] == win.start.date() and params["end_date"] == win.end.date():
                    merged = df.merge(plan[["sku_id", "avg_daily_demand"]], on="sku_id", suffixes=("_sql", "_py"))
                    diff = (merged["avg_daily_demand_sql"] - merged["avg_daily_demand_py"]).abs().max()
                    st.success(f"Reconciliation: max difference in average daily demand {diff:.5f} units "
                               "(SQL rounds to 4 decimals).")
