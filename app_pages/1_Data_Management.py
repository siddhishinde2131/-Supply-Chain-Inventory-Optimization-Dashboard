"""Page 1 - Home & Data Management: data source, uploads, validation, settings."""
import io
from dataclasses import replace

import pandas as pd
import streamlit as st

from src.analytics.demand import data_gap_days, flag_outliers
from src.config import AnalysisSettings, settings_as_rows
from src.data.loader import dataset_from_frames, dataset_from_sources, load_sample_dataset
from src.data.quality import column_profile, missing_values_table, quality_summary
from src.data.schema import FILE_SPECS, schema_table, template_csv
from src.database import repository as repo
from src.database.connection import DatabaseError, DbConfig, config_from_env, connection, check_connection
from src.reporting.exports import data_quality_report
from src.ui import auth
from src.ui.components import download_button, page_header
from src.ui.theme import card
from src.ui.state import get_dataset, get_result, get_settings, set_dataset, set_settings

page_header("Supply Chain & Inventory Optimization Dashboard",
            "Reduce excess stock, spot potential stock-outs and plan replenishment from your "
            "own data. Every number in this app is calculated from the loaded dataset.")

user = st.session_state.get(auth.SESSION_KEY) or {}
if user:
    st.markdown(f"#### Welcome, {user['display_name']}")

if get_dataset() is None:
    steps = st.columns(3)
    with steps[0]:
        card("Choose a mode", "CSV mode works instantly. PostgreSQL mode stores the data in "
             "relational tables and unlocks SQL analytics.", "Step 1")
    with steps[1]:
        card("Load data", "Use the synthetic sample dataset or upload your own products, sales, "
             "suppliers and purchase-order CSV files.", "Step 2")
    with steps[2]:
        card("Explore & plan", "Review KPIs, ABC/XYZ classes, reorder alerts and scenarios, then "
             "download the reports.", "Step 3")
    st.write("")

with st.expander(":material/info: What can each page do?", expanded=False):
    features = st.columns(3)
    items = [
        ("Executive Overview", "Inventory value, holding cost, turnover and alerts at a glance."),
        ("Inventory Analysis", "Product search, stock levels, demand trends, excess stock and SQL."),
        ("ABC/XYZ Analysis", "Which products matter most and which are predictable."),
        ("Replenishment Planning", "Safety stock, reorder points and suggested order quantities."),
        ("Scenario Analysis", "The cost of 90% vs 95% vs 99% service levels."),
        ("Business Insights", "Products at risk, excess stock, supplier issues and all reports."),
    ]
    for i, (title, body) in enumerate(items):
        with features[i % 3]:
            card(title, body)
            st.write("")


# ---------------------------------------------------------------------------
# Validation report
# ---------------------------------------------------------------------------
def render_validation(validation) -> None:
    summary = quality_summary(validation)
    st.dataframe(summary, hide_index=True, width="stretch")
    for error in validation.blocking_errors:
        st.error(error, icon=":material/error:")
    issues = validation.issue_summary()
    if issues.empty:
        st.success("No row-level problems found.", icon=":material/check_circle:")
    else:
        errors = issues[issues["severity"] == "error"]["rows_affected"].sum()
        warnings = issues[issues["severity"] == "warning"]["rows_affected"].sum()
        st.warning(f"{errors:,} row problem(s) cause exclusions and {warnings:,} warning(s) were "
                   "found (warning rows are kept). Details below.", icon=":material/warning:")
        st.dataframe(issues, hide_index=True, width="stretch")
        with st.expander("Row-level details and how to fix them"):
            st.dataframe(validation.issues_frame(), hide_index=True, width="stretch")
    with st.expander("Missing values per column"):
        st.dataframe(missing_values_table(validation), hide_index=True, width="stretch",
                     column_config={"missing_pct": st.column_config.NumberColumn(format="percent")})


def accept_dataset(dataset, validation, message: str) -> None:
    set_dataset(dataset, validation)
    st.session_state.pop("pending", None)
    st.success(message, icon=":material/check_circle:")


# ---------------------------------------------------------------------------
# 1. Operating mode
# ---------------------------------------------------------------------------
st.header("1. Choose an operating mode")
mode = st.radio("Operating mode", ["CSV mode (no database needed)", "PostgreSQL mode"],
                key="operating_mode", horizontal=True,
                help="CSV mode keeps everything in memory. PostgreSQL mode stores the data in "
                     "relational tables and enables the SQL analytics.")

if mode.startswith("CSV"):
    st.header("2. Choose the data")
    source = st.radio("Data source", ["Use Sample Dataset", "Upload My Own Data"],
                      key="csv_source", horizontal=True)
    if source == "Use Sample Dataset":
        st.info("The sample dataset is **synthetic** (generated with a fixed random seed): "
                "2,400 SKUs, 40 suppliers, 365 days of daily sales and ~7,000 purchase orders. "
                "It deliberately contains a few duplicate and negative sales rows so you can see "
                "the validation in action.", icon=":material/science:")
        if st.button("Load sample dataset", type="primary", icon=":material/play_arrow:"):
            with st.spinner("Loading and validating the sample dataset..."):
                dataset, validation = load_sample_dataset()
            if dataset is None:
                st.error("The sample dataset could not be loaded.")
                render_validation(validation)
            else:
                accept_dataset(dataset, validation,
                               f"Sample dataset loaded: {len(dataset.products):,} SKUs, "
                               f"{len(dataset.sales):,} daily sales records.")
    else:
        st.markdown("Upload **Products & Inventory**, **Sales History** and **Suppliers** "
                    "(required) and optionally **Purchase Orders**. Files are read in memory "
                    "only - your original files are never changed.")
        with st.expander(":material/description: Templates and column definitions", expanded=False):
            template_cols = st.columns(len(FILE_SPECS))
            for col, spec in zip(template_cols, FILE_SPECS.values()):
                col.download_button(f"{spec.label} template", template_csv(spec),
                                    file_name=f"template_{spec.key}.csv", mime="text/csv",
                                    key=f"tpl_{spec.key}", icon=":material/download:")
            st.caption("Dates must use YYYY-MM-DD. Numbers use '.' as decimal separator and "
                       "no currency symbols. Common alternative column names (e.g. 'sku', "
                       "'qty', 'date') are recognised automatically.")
            for spec in FILE_SPECS.values():
                st.markdown(f"**{spec.label}** ({'required' if spec.required else 'optional'}) - "
                            f"{spec.description}")
                st.dataframe(pd.DataFrame(schema_table(spec)), hide_index=True, width="stretch")

        uploads = {}
        upload_cols = st.columns(2)
        for i, spec in enumerate(FILE_SPECS.values()):
            with upload_cols[i % 2]:
                file = st.file_uploader(f"{spec.label}{'' if spec.required else ' (optional)'}",
                                        type=["csv"], key=f"upload_{spec.key}")
                if file is not None:
                    uploads[spec.key] = file.getvalue()

        if uploads:
            st.subheader("Preview")
            tabs = st.tabs([FILE_SPECS[k].label for k in uploads])
            for tab, (key, data) in zip(tabs, uploads.items()):
                with tab:
                    try:
                        preview = pd.read_csv(io.BytesIO(data), dtype=str, nrows=20)
                        st.dataframe(preview, hide_index=True, width="stretch")
                    except Exception as exc:  # preview only; validation reports the details
                        st.error(f"Preview not possible: {exc}")

        missing_required = [s.label for s in FILE_SPECS.values() if s.required and s.key not in uploads]
        if missing_required:
            st.caption("Still needed: " + ", ".join(missing_required))
        if st.button("Validate files", type="primary", disabled=not uploads,
                     icon=":material/fact_check:"):
            with st.spinner("Validating uploaded files..."):
                dataset, validation = dataset_from_sources(uploads, "Uploaded dataset", "upload_csv")
            st.session_state["pending"] = (dataset, validation)

        pending = st.session_state.get("pending")
        if pending:
            dataset, validation = pending
            st.subheader("Validation report")
            render_validation(validation)
            if dataset is None:
                st.error("The files cannot be analysed yet. Fix the problems listed above and "
                         "upload the corrected files.", icon=":material/block:")
            else:
                excluded = validation.excluded_total
                confirmed = True
                if excluded:
                    confirmed = st.checkbox(
                        f"I understand that {excluded:,} invalid row(s) will be excluded from "
                        "the analysis.", key="confirm_exclusions")
                if st.button("Use this data for analysis", type="primary", disabled=not confirmed,
                             icon=":material/check:"):
                    accept_dataset(dataset, validation,
                                   f"Uploaded data loaded: {len(dataset.products):,} SKUs.")

else:
    # -----------------------------------------------------------------------
    # PostgreSQL mode
    # -----------------------------------------------------------------------
    st.header("2. Connect to PostgreSQL")
    st.caption("Defaults come from environment variables / the .env file (PGHOST, PGPORT, "
               "PGDATABASE, PGUSER, PGPASSWORD). Leave the password field empty to use the "
               "value from .env — it is never shown here.")
    try:
        env_config = config_from_env()
    except DatabaseError as exc:
        st.error(str(exc))
        env_config = DbConfig()
    current = st.session_state.get("db_config", env_config)
    with st.form("db_form"):
        c1, c2, c3 = st.columns([2, 1, 2])
        host = c1.text_input("Host", current.host)
        port = c2.number_input("Port", 1, 65535, current.port)
        dbname = c3.text_input("Database", current.dbname)
        c4, c5 = st.columns(2)
        user = c4.text_input("User", current.user)
        password = c5.text_input("Password", "", type="password",
                                 placeholder="(leave blank to use .env value)")
        submitted = st.form_submit_button("Test connection", icon=":material/lan:")
    if submitted:
        # Blank field means "use the .env password" — never echo the credential.
        effective_password = password if password else env_config.password
        st.session_state["db_config"] = DbConfig(host, int(port), dbname, user,
                                                 effective_password, current.sslmode)
        ok, message = check_connection(st.session_state["db_config"])
        st.session_state["db_ok"] = ok
        st.session_state["db_message"] = message
    if "db_message" in st.session_state:
        if st.session_state.get("db_ok"):
            st.success(st.session_state["db_message"], icon=":material/check_circle:")
        else:
            st.error(st.session_state["db_message"], icon=":material/error:")
            st.info("PostgreSQL mode is unavailable until the connection works. The app will "
                    "not switch data source on its own - select **CSV mode** above to continue "
                    "without a database.")

    if st.session_state.get("db_ok"):
        cfg = st.session_state["db_config"]
        try:
            with connection(cfg) as conn:
                has_schema = repo.schema_exists(conn)
                counts = repo.table_counts(conn) if has_schema else None
                info = repo.stored_dataset_info(conn) if has_schema else None
        except DatabaseError as exc:
            st.error(str(exc))
            st.stop()

        st.header("3. Manage stored data")
        if not has_schema:
            st.warning("The tables do not exist yet in this database.")
        admin = auth.is_admin()
        if not admin:
            st.caption(":material/lock: Creating tables and storing data are administrator actions. "
                       "You can analyse the data already stored.")
        if st.button("Create / update tables (sql/schema.sql)", icon=":material/table:",
                     disabled=not admin):
            try:
                with connection(cfg) as conn:
                    repo.create_schema(conn)
                st.success("Tables are ready.")
                st.rerun()
            except DatabaseError as exc:
                st.error(str(exc))

        if has_schema:
            c1, c2 = st.columns([1, 2])
            c1.dataframe(counts, hide_index=True)
            if info:
                kind = "SYNTHETIC sample data" if info["is_synthetic"] else "user-provided data"
                c2.info(f"Stored dataset: **{info['label']}** ({kind}), saved "
                        f"{info['loaded_at']:%Y-%m-%d %H:%M}.")
            else:
                c2.info("No dataset stored yet.")

            def store(dataset, label):
                try:
                    with st.spinner(f"Writing {label} to PostgreSQL (replaces stored data)..."):
                        with connection(cfg) as conn:
                            written = repo.save_dataset(conn, dataset)
                    st.success("Stored: " + ", ".join(f"{t} {n:,}" for t, n in written.items()))
                except (DatabaseError, ValueError) as exc:
                    st.error(str(exc))

            st.caption("Storing data **replaces** everything currently in the tables.")
            b1, b2, b3 = st.columns(3)
            if b1.button("Store the sample dataset", icon=":material/science:", disabled=not admin):
                dataset, _ = load_sample_dataset()
                store(dataset, "the sample dataset")
            loaded = get_dataset()
            if b2.button("Store the currently loaded dataset", icon=":material/upload:",
                         disabled=not admin or loaded is None or loaded.source_type == "postgresql",
                         help="Load or upload data in CSV mode first, then store it here."):
                store(loaded, loaded.label)
            if b3.button("Analyse data stored in PostgreSQL", type="primary",
                         icon=":material/play_arrow:", disabled=not info):
                try:
                    with st.spinner("Reading tables and validating..."):
                        with connection(cfg) as conn:
                            frames = repo.load_raw_frames(conn)
                        dataset, validation = dataset_from_frames(
                            frames, f"{info['label']} (PostgreSQL)", "postgresql",
                            info["is_synthetic"])
                    if dataset is None:
                        st.error("Stored data failed validation.")
                        render_validation(validation)
                    else:
                        accept_dataset(dataset, validation,
                                       f"Loaded {len(dataset.products):,} SKUs from PostgreSQL.")
                except DatabaseError as exc:
                    st.error(str(exc))

# ---------------------------------------------------------------------------
# Current dataset: validation report, profile, settings
# ---------------------------------------------------------------------------
dataset = get_dataset()
if dataset is None:
    st.stop()

st.divider()
st.header("Current dataset")
period = dataset.sales_period
c1, c2, c3, c4 = st.columns(4)
c1.metric("Products (SKUs)", f"{len(dataset.products):,}")
c2.metric("Daily sales records", f"{len(dataset.sales):,}")
c3.metric("Suppliers", f"{len(dataset.suppliers):,}")
c4.metric("Purchase orders", f"{len(dataset.purchase_orders):,}" if dataset.has_purchase_orders
          else "Not provided")
if period:
    st.caption(f"Sales history: {period[0]:%Y-%m-%d} to {period[1]:%Y-%m-%d} "
               f"({(period[1] - period[0]).days + 1} days).")
for note in dataset.notes:
    st.caption(f":material/info: {note}")

tab_quality, tab_preview, tab_settings = st.tabs(
    ["Data-quality report", "Data preview & structure", "Analysis settings"])

with tab_quality:
    validation = dataset.validation
    render_validation(validation)
    result = get_result(dataset)
    gaps = data_gap_days(dataset.sales, result.window)
    outliers = flag_outliers(dataset.sales, result.prepared.classified, result.window)
    g1, g2 = st.columns(2)
    g1.metric("Days with no sales for any SKU", f"{len(gaps):,}",
              help="Possible data gaps. With the default policy these days count as zero demand.")
    g2.metric("Outlier sales days (flagged, not removed)", f"{len(outliers):,}",
              help="Days where a SKU sold more than its mean + 4 standard deviations.")
    if len(gaps):
        st.warning("Days without any sales: " + ", ".join(f"{d:%Y-%m-%d}" for d in gaps[:20])
                   + (" ..." if len(gaps) > 20 else ""))
    if len(outliers):
        with st.expander("Outlier sales days"):
            st.dataframe(outliers.sort_values("quantity_sold", ascending=False).head(500),
                         hide_index=True, width="stretch")
    download_button(data_quality_report(validation), "data_quality_report",
                    "Download data-quality report", dataset, "dl_quality")

with tab_preview:
    names = {"Products & Inventory": dataset.products, "Daily sales": dataset.sales,
             "Suppliers": dataset.suppliers}
    if dataset.has_purchase_orders:
        names["Purchase orders"] = dataset.purchase_orders
    choice = st.selectbox("Table", list(names))
    frame = names[choice]
    st.dataframe(frame.head(200), hide_index=True, width="stretch")
    st.caption(f"First 200 of {len(frame):,} rows. Column structure:")
    st.dataframe(column_profile(frame), hide_index=True, width="stretch")

with tab_settings:
    settings = get_settings()
    st.caption("These assumptions drive every calculation. Changes apply to all pages.")
    with st.form("settings_form"):
        c1, c2, c3 = st.columns(3)
        analysis_days = c1.number_input("Analysis period (days of history)", 7, 3650,
                                        settings.analysis_days,
                                        help="Window ending on the last sales date. Shorter "
                                             "history is used as available.")
        min_history = c1.number_input("Minimum history for XYZ (days)", 2, 365,
                                      settings.min_history_days)
        zero_fill = c1.checkbox("Treat days without a sales record as zero demand",
                                settings.missing_days_as_zero,
                                help="Recommended when the sales file lists every sale. "
                                     "Untick if missing days may be missing data.")
        a_thr = c2.number_input("ABC: A up to cumulative value (%)", 1.0, 99.0,
                                settings.abc_a_threshold * 100, step=1.0)
        b_thr = c2.number_input("ABC: B up to cumulative value (%)", 2.0, 99.9,
                                settings.abc_b_threshold * 100, step=1.0)
        x_thr = c2.number_input("XYZ: X if CV <=", 0.05, 5.0, settings.xyz_x_threshold, step=0.05)
        y_thr = c2.number_input("XYZ: Y if CV <=", 0.1, 10.0, settings.xyz_y_threshold, step=0.05)
        holding = c3.number_input("Annual holding-cost rate (%)", 0.0, 100.0,
                                  settings.holding_cost_rate * 100, step=1.0,
                                  help="Storage, capital, insurance and obsolescence cost per year "
                                       "as % of inventory value.")
        coverage = c3.number_input("Target coverage after reorder (days)", 0, 365,
                                   settings.target_coverage_days)
        excess = c3.number_input("Excess buffer above target (days)", 0, 730,
                                 settings.excess_buffer_days)
        use_lt_var = c3.checkbox("Use lead-time variability when available",
                                 settings.use_lead_time_variability)
        currency = c3.text_input("Currency symbol", settings.currency_symbol, max_chars=3)
        saved = st.form_submit_button("Apply settings", type="primary")
    if saved:
        new = replace(settings, analysis_days=int(analysis_days), min_history_days=int(min_history),
                      missing_days_as_zero=zero_fill, abc_a_threshold=a_thr / 100,
                      abc_b_threshold=b_thr / 100, xyz_x_threshold=x_thr, xyz_y_threshold=y_thr,
                      holding_cost_rate=holding / 100, target_coverage_days=int(coverage),
                      excess_buffer_days=int(excess), use_lead_time_variability=use_lt_var,
                      currency_symbol=currency)
        problems = new.validate()
        if problems:
            for p in problems:
                st.error(p)
        else:
            set_settings(new)
            st.success("Settings applied.")
            st.rerun()
    if st.button("Reset all settings to defaults", icon=":material/restart_alt:"):
        set_settings(replace(AnalysisSettings(), service_level=settings.service_level))
        st.rerun()
    st.dataframe(pd.DataFrame(settings_as_rows(get_settings())).astype(str),
                 hide_index=True, width="stretch")
