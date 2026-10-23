"""Streamlit session state: current dataset, settings and memoised analysis.

Results are memoised per (dataset_id, settings). Loading a new dataset creates a
new dataset_id and clears the memo, so results can never be stale.
"""
import streamlit as st
from streamlit.errors import StreamlitPageNotFoundError

from src.analytics.pipeline import (AnalysisResult, PreparedAnalysis, prepare_analysis,
                                    preparation_key, run_plan)
from src.config import AnalysisSettings
from src.data.cleaning import Dataset

MEMO_LIMIT = 8


def get_settings() -> AnalysisSettings:
    return st.session_state.get("settings", AnalysisSettings())


def set_settings(settings: AnalysisSettings) -> None:
    st.session_state["settings"] = settings


def get_dataset() -> Dataset | None:
    return st.session_state.get("dataset")


def set_dataset(dataset: Dataset | None, validation=None) -> None:
    st.session_state["dataset"] = dataset
    st.session_state["validation"] = validation if validation is not None else (
        dataset.validation if dataset else None)
    st.session_state["_memo"] = {}


def _memo(key, compute):
    cache = st.session_state.setdefault("_memo", {})
    if key not in cache:
        if len(cache) >= MEMO_LIMIT:
            cache.pop(next(iter(cache)))
        cache[key] = compute()
    return cache[key]


def get_prepared(dataset: Dataset, settings: AnalysisSettings) -> PreparedAnalysis:
    key = ("prepared", dataset.dataset_id, preparation_key(settings))
    with st.spinner("Calculating demand statistics and ABC/XYZ classes..."):
        return _memo(key, lambda: prepare_analysis(dataset, settings))


def get_result(dataset: Dataset, settings: AnalysisSettings | None = None) -> AnalysisResult:
    settings = settings or get_settings()
    prepared = get_prepared(dataset, settings)
    return _memo(("plan", dataset.dataset_id, settings), lambda: run_plan(prepared, settings))


def require_result() -> tuple[Dataset, AnalysisResult]:
    """Return (dataset, result) or show a friendly message and stop the page."""
    dataset = get_dataset()
    if dataset is None:
        st.info("No data loaded yet. Go to **Home & Data Management** and choose the sample "
                "dataset or upload your own CSV files.")
        try:
            st.page_link("app_pages/1_Data_Management.py", label="Go to Home & Data Management",
                         icon=":material/home:")
        except StreamlitPageNotFoundError:
            pass  # page run outside the navigation of app.py (e.g. in tests)
        st.stop()
    return dataset, get_result(dataset)
