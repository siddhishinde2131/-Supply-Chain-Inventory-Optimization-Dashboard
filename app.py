"""Supply Chain & Inventory Optimization Dashboard - Streamlit entry point.

Run with:  streamlit run app.py

Only the sign-in page exists until a user is authenticated, so no analysis page
or data can be reached without logging in.
"""
from dataclasses import replace

import streamlit as st

from src.ui import auth
from src.ui.state import get_dataset, get_settings, set_settings
from src.config import PROJECT_ROOT
from src.ui.components import fmt_level
from src.ui.theme import inject_css

st.set_page_config(page_title="Inventory Optimization Dashboard", page_icon=":material/inventory_2:",
                   layout="wide")
inject_css()
st.logo(str(PROJECT_ROOT / "assets" / "logo.svg"), size="large",
        icon_image=str(PROJECT_ROOT / "assets" / "logo_icon.svg"))

user = auth.current_user()
if user is None:
    st.navigation([st.Page(auth.login_page, title="Sign in", icon=":material/login:")],
                  position="hidden").run()
    st.stop()

PAGES = {
    "Data": [
        st.Page("app_pages/1_Data_Management.py", title="Home & Data Management", icon=":material/home:",
                default=True),
    ],
    "Analysis": [
        st.Page("app_pages/2_Executive_Overview.py", title="Executive Overview", icon=":material/dashboard:"),
        st.Page("app_pages/3_Inventory_Analysis.py", title="Inventory Analysis", icon=":material/inventory:"),
        st.Page("app_pages/4_ABC_XYZ_Analysis.py", title="ABC/XYZ Analysis", icon=":material/grid_view:"),
    ],
    "Planning": [
        st.Page("app_pages/5_Replenishment_Planning.py", title="Replenishment Planning",
                icon=":material/local_shipping:"),
        st.Page("app_pages/6_Scenario_Analysis.py", title="Scenario Analysis", icon=":material/tune:"),
        st.Page("app_pages/7_Business_Insights.py", title="Business Insights & Reports",
                icon=":material/insights:"),
    ],
    "Account": [
        st.Page("app_pages/8_Account.py", title="Account & Users" if user["role"] == "admin" else "My Account",
                icon=":material/manage_accounts:"),
    ],
}
navigation = st.navigation(PAGES)

SERVICE_LEVEL_OPTIONS = [0.85, 0.90, 0.95, 0.975, 0.99]

with st.sidebar:
    auth.user_card()
    st.divider()
    dataset = get_dataset()
    if dataset is None:
        st.warning("No data loaded", icon=":material/database_off:")
    elif dataset.is_synthetic:
        st.info(f"**{dataset.label}**  \nSYNTHETIC data, for demonstration only.",
                icon=":material/science:")
    else:
        st.success(f"**{dataset.label}**  \nUser-provided data.", icon=":material/database:")
    if dataset is not None:
        mode = "PostgreSQL mode" if dataset.source_type == "postgresql" else "CSV mode"
        st.caption(f"{mode} - loaded {dataset.loaded_at:%Y-%m-%d %H:%M}")

    settings = get_settings()
    if st.session_state.get("service_level_widget") not in SERVICE_LEVEL_OPTIONS:
        st.session_state["service_level_widget"] = (
            settings.service_level if settings.service_level in SERVICE_LEVEL_OPTIONS else 0.95)
    level = st.select_slider(
        "Target service level", options=SERVICE_LEVEL_OPTIONS, key="service_level_widget",
        format_func=fmt_level,
        help="Probability of not running out of stock during a replenishment cycle. "
             "Higher = more safety stock. Safety stock, reorder points and alerts on every "
             "page recalculate immediately.")
    if level != settings.service_level:
        set_settings(replace(settings, service_level=level))
    st.caption(f"Session ends after {auth.session_timeout_minutes()} minutes of inactivity.")

navigation.run()
