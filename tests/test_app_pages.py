"""Smoke tests: every Streamlit page runs without exceptions on the sample data."""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parent.parent
PAGES = sorted(str(p.relative_to(ROOT)) for p in (ROOT / "app_pages").glob("*.py"))


def _run(page: str, dataset=None) -> AppTest:
    at = AppTest.from_file(str(ROOT / page), default_timeout=180)
    if dataset is not None:
        at.session_state["dataset"] = dataset
        at.session_state["validation"] = dataset.validation
    return at.run()


@pytest.mark.parametrize("page", PAGES)
def test_page_runs_with_sample_data(page, sample_dataset):
    at = _run(page, sample_dataset)
    assert not at.exception, [e.value for e in at.exception]


def test_app_entry_point_requires_login(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTH_USERS_FILE", str(tmp_path / "users.json"))
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60).run()
    assert not at.exception, [e.value for e in at.exception]
    assert "auth_user" not in at.session_state      # only the sign-in / setup screen is shown


def test_analysis_page_without_data_shows_guidance():
    at = _run("app_pages/2_Executive_Overview.py")
    assert not at.exception
    assert any("No data loaded" in i.value for i in at.info)


def test_service_level_change_updates_replenishment_page(sample_dataset):
    """Changing the service level must change the reorder count shown on the page."""
    from dataclasses import replace

    from src.config import AnalysisSettings

    values = []
    for level in (0.90, 0.99):
        at = AppTest.from_file(str(ROOT / "app_pages/5_Replenishment_Planning.py"), default_timeout=180)
        at.session_state["dataset"] = sample_dataset
        at.session_state["settings"] = replace(AnalysisSettings(), service_level=level)
        at.run()
        assert not at.exception
        values.append(next(m.value for m in at.metric if m.label == "Reorder Required"))
    assert int(values[0].replace(",", "")) < int(values[1].replace(",", ""))


def test_load_sample_button_loads_dataset():
    at = AppTest.from_file(str(ROOT / "app_pages/1_Data_Management.py"), default_timeout=180).run()
    next(b for b in at.button if b.label == "Load sample dataset").click().run()
    assert not at.exception
    assert at.session_state["dataset"].is_synthetic
    assert any("Sample dataset loaded" in s.value for s in at.success)


@pytest.mark.skipif(not __import__("os").getenv("TEST_PGHOST"),
                    reason="set TEST_PGHOST to run the PostgreSQL UI workflow")
def test_postgresql_mode_workflow(monkeypatch):
    import os

    for name in ("HOST", "PORT", "DATABASE", "USER", "PASSWORD"):
        value = os.getenv(f"TEST_PG{name}")
        if value is not None:
            monkeypatch.setenv(f"PG{name}", value)
    at = AppTest.from_file(str(ROOT / "app_pages/1_Data_Management.py"), default_timeout=300)
    at.session_state["auth_user"] = {"username": "admin", "display_name": "Admin", "role": "admin"}
    at.run()
    at.radio(key="operating_mode").set_value("PostgreSQL mode").run()
    next(b for b in at.button if b.label == "Test connection").click().run()
    assert any("Connected to" in s.value for s in at.success), [e.value for e in at.error]
    next(b for b in at.button if b.label.startswith("Create / update tables")).click().run()
    next(b for b in at.button if b.label == "Store the sample dataset").click().run()
    assert any(s.value.startswith("Stored:") for s in at.success), [e.value for e in at.error]
    next(b for b in at.button if b.label == "Analyse data stored in PostgreSQL").click().run()
    assert not at.exception
    dataset = at.session_state["dataset"]
    assert dataset.source_type == "postgresql" and dataset.is_synthetic

    # SQL analytics tab on the Inventory Analysis page, with reconciliation
    page = AppTest.from_file(str(ROOT / "app_pages/3_Inventory_Analysis.py"), default_timeout=300)
    for key in ("dataset", "db_ok", "db_config"):
        page.session_state[key] = at.session_state[key]
    page.run()
    page.selectbox(key="sql_query").set_value("abc_support").run()
    next(b for b in page.button if b.label == "Run query").click().run()
    assert not page.exception
    assert any("agree for 100.00%" in s.value for s in page.success), [s.value for s in page.success]


def test_failed_connection_is_reported_without_switching_source(monkeypatch):
    monkeypatch.setenv("PGHOST", "127.0.0.1")
    monkeypatch.setenv("PGPORT", "1")
    at = AppTest.from_file(str(ROOT / "app_pages/1_Data_Management.py"), default_timeout=60).run()
    at.radio(key="operating_mode").set_value("PostgreSQL mode").run()
    next(b for b in at.button if b.label == "Test connection").click().run()
    assert not at.exception
    assert any("Cannot reach PostgreSQL" in e.value for e in at.error)
    assert any("will not switch data source" in i.value for i in at.info)
    assert at.session_state["dataset"] is None if "dataset" in at.session_state else True
