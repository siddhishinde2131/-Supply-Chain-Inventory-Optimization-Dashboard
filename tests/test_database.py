"""Database error handling, plus integration tests against a real PostgreSQL.

Integration tests run only when TEST_PGHOST (and optionally TEST_PGPORT,
TEST_PGDATABASE, TEST_PGUSER, TEST_PGPASSWORD) point to a DISPOSABLE database -
they replace all data in its tables.
"""
import os

import pytest

from src.database import repository as repo
from src.database.connection import DatabaseError, DbConfig, config_from_env, connection, check_connection
from tests.helpers import build, daily_sales


def test_unreachable_server_gives_friendly_error():
    ok, message = check_connection(DbConfig(host="127.0.0.1", port=1, dbname="x", user="x"))
    assert not ok
    assert "Cannot reach PostgreSQL" in message


def test_invalid_port_in_environment(monkeypatch):
    monkeypatch.setenv("BADPGPORT", "not-a-number")
    with pytest.raises(DatabaseError):
        config_from_env(prefix="BADPG")


def test_password_is_not_in_description():
    assert "secret" not in DbConfig(password="secret").describe()


def test_referential_integrity_check_blocks_unknown_suppliers():
    dataset, _ = build("""sku_id,product_name,category,unit_cost,selling_price,on_hand_qty,supplier_id,snapshot_date
        A,One,Cat,10,20,5,S9,2026-01-31""", "2026-01-01,A,3",
                       "supplier_id,supplier_name,avg_lead_time_days\nS1,One,5")
    assert repo.check_referential_integrity(dataset)


needs_db = pytest.mark.skipif(not os.getenv("TEST_PGHOST"),
                              reason="set TEST_PGHOST to run PostgreSQL integration tests")


@needs_db
def test_round_trip_and_sql_matches_python():
    from src.analytics.pipeline import run_analysis
    from src.config import AnalysisSettings
    from src.data.loader import dataset_from_frames

    cfg = config_from_env(prefix="TEST_PG")
    products = """sku_id,product_name,category,unit_cost,selling_price,on_hand_qty,supplier_id,snapshot_date
        A,One,Cat1,10,20,5,S1,2026-01-31
        B,Two,Cat2,4,8,50,S1,2026-01-31
        C,Three,Cat2,1,2,7,S1,2026-01-31"""
    sales = "\n".join([daily_sales("A", [3, 1] * 15), daily_sales("B", [1, None] * 15)])
    dataset, _ = build(products, sales, "supplier_id,supplier_name,avg_lead_time_days\nS1,One,5")
    with connection(cfg) as conn:
        repo.create_schema(conn)
        written = repo.save_dataset(conn, dataset)
        assert written["products"] == 3
    with connection(cfg) as conn:
        frames = repo.load_raw_frames(conn)
        info = repo.stored_dataset_info(conn)
    reloaded, _ = dataset_from_frames(frames, info["label"], "postgresql", info["is_synthetic"])
    settings = AnalysisSettings()
    original, again = run_analysis(dataset, settings), run_analysis(reloaded, settings)
    assert original.kpis == again.kpis

    w = original.window
    with connection(cfg) as conn:
        abc = repo.run_query(conn, "abc_support", {
            "start_date": w.start.date(), "end_date": w.end.date(),
            "annual_factor": w.annualisation_factor, "a_threshold": 0.8, "b_threshold": 0.95})
        by_cat = repo.run_query(conn, "inventory_value_by_category")
        repo.save_inventory_metrics(conn, original.plan)
        below = repo.run_query(conn, "products_below_reorder_point", {"limit": 10})
    python_abc = original.plan.set_index("sku_id")["abc_class"]
    assert abc.set_index("sku_id")["abc_class"].to_dict() == python_abc.to_dict()
    assert by_cat.set_index("category")["inventory_value"].to_dict() == {"Cat1": 50.0, "Cat2": 207.0}
    expected_below = set(original.plan.loc[original.plan["alert_status"] == "Reorder Required", "sku_id"])
    assert set(below["sku_id"]) == expected_below
