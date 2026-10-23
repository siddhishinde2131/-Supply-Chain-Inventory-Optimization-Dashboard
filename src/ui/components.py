"""Reusable Streamlit components: headers, KPI formatting, filters, downloads."""
import math

import pandas as pd
import streamlit as st

from src.analytics.classification import ABC_CLASSES, INSUFFICIENT, NO_DEMAND, XYZ_CLASSES
from src.inventory.planning import ALERT_STATUSES
from src.reporting.exports import report_filename, to_csv_bytes
from src.ui.theme import hero


def page_header(title: str, description: str) -> None:
    """Hero card with chips showing what data and service level are being analysed."""
    dataset = st.session_state.get("dataset")
    if dataset is None:
        chips = [("No data loaded", "none")]
    else:
        kind = ("SYNTHETIC sample data", "synthetic") if dataset.is_synthetic             else ("User-provided data", "user")
        mode = "PostgreSQL mode" if dataset.source_type == "postgresql" else "CSV mode"
        chips = [kind, (dataset.label, ""), (mode, ""),
                 (f"{len(dataset.products):,} SKUs", "")]
    settings = st.session_state.get("settings")
    level = settings.service_level if settings else 0.95
    chips.append((f"Service level {fmt_level(level)}", ""))
    hero(title, description, chips)


def is_missing(value) -> bool:
    return value is None or (isinstance(value, float) and math.isnan(value))


def fmt_money(value, symbol: str = "$", decimals: int = 0) -> str:
    if is_missing(value):
        return "Not available"
    sign = "-" if value < 0 else ""
    value = abs(value)
    if value >= 1e6:
        return f"{sign}{symbol}{value / 1e6:,.2f}M"
    if value >= 1e4:
        return f"{sign}{symbol}{value / 1e3:,.1f}K"
    return f"{sign}{symbol}{value:,.{decimals}f}"


def fmt_num(value, decimals: int = 0) -> str:
    return "Not available" if is_missing(value) else f"{value:,.{decimals}f}"


def fmt_level(value: float) -> str:
    """Service level as 95% or 97.5% (no trailing .0)."""
    return f"{value:.1%}" if round(value * 1000) % 10 else f"{value:.0%}"


def fmt_pct(value, decimals: int = 1) -> str:
    return "Not available" if is_missing(value) else f"{value:.{decimals}%}"


def empty_state(message: str = "No records match the selected filters.") -> None:
    st.info(f":material/filter_alt_off: {message} Try widening the filters.")


def filter_bar(df: pd.DataFrame, key: str,
               fields=("search", "category", "supplier", "abc", "xyz", "status")) -> pd.DataFrame:
    """Render filters in one row above the content and return the filtered frame."""
    options = {
        "category": ("Category", "category", sorted(df["category"].dropna().unique())),
        "supplier": ("Supplier", "supplier_id", sorted(df["supplier_id"].dropna().unique())),
        "abc": ("ABC class", "abc_class",
                [c for c in ABC_CLASSES + (INSUFFICIENT,) if c in set(df["abc_class"])]),
        "xyz": ("XYZ class", "xyz_class",
                [c for c in XYZ_CLASSES + (NO_DEMAND, INSUFFICIENT) if c in set(df["xyz_class"])]),
        "status": ("Stock status", "alert_status",
                   [s for s in ALERT_STATUSES if s in set(df["alert_status"])]),
    }
    columns = st.columns(len(fields))
    mask = pd.Series(True, index=df.index)
    for col, name in zip(columns, fields):
        with col:
            if name == "search":
                text = st.text_input("Search SKU / product", key=f"{key}_search",
                                     placeholder="e.g. SKU-00012 or Kettle").strip()
                if text:
                    mask &= (df["sku_id"].str.contains(text, case=False, regex=False)
                             | df["product_name"].str.contains(text, case=False, regex=False))
            else:
                label, column, values = options[name]
                chosen = st.multiselect(label, values, key=f"{key}_{name}", placeholder="All")
                if chosen:
                    mask &= df[column].isin(chosen)
    filtered = df[mask]
    st.caption(f"Showing {len(filtered):,} of {len(df):,} products.")
    return filtered


def download_button(frame: pd.DataFrame, report: str, label: str, dataset, key: str,
                    suffix: str = "") -> None:
    st.download_button(
        label=f":material/download: {label}", data=to_csv_bytes(frame),
        file_name=report_filename(report, dataset.label, suffix), mime="text/csv",
        key=key, disabled=frame.empty,
        help=f"{len(frame):,} rows. Reflects the current dataset and filters.")


def money_column(symbol: str = "$", label: str | None = None):
    """Currency column with thousands separators (Streamlit preset formats)."""
    if symbol == "$":
        return st.column_config.NumberColumn(label, format="dollar")
    return st.column_config.NumberColumn(f"{label} ({symbol})" if label else None,
                                         format="localized")


def units_column(label: str | None = None, decimals: int = 0):
    return st.column_config.NumberColumn(label, format="localized" if decimals == 0
                                         else f"%.{decimals}f")


def share_column(label: str | None = None):
    return st.column_config.ProgressColumn(label, format="percent", min_value=0, max_value=1)


def formula_note(title: str, body: str) -> None:
    with st.expander(f":material/function: {title}"):
        st.markdown(body)
