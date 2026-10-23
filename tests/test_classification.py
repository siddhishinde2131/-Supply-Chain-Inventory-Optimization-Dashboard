"""ABC/XYZ classification and demand statistics."""
import math

import pandas as pd
import pytest

from src.analytics.classification import INSUFFICIENT, NO_DEMAND, abc_classify, xyz_classify
from src.analytics.demand import demand_statistics
from src.config import AnalysisSettings


def test_abc_cumulative_thresholds():
    # shares 50, 30, 10, 5, 3, 2 -> cumulative before: 0, 50, 80, 90, 95, 98
    values = pd.Series({"a": 50, "b": 30, "c": 10, "d": 5, "e": 3, "f": 2})
    result = abc_classify(values, 0.80, 0.95)
    assert result["abc_class"].to_dict() == {"a": "A", "b": "A", "c": "B", "d": "B",
                                             "e": "C", "f": "C"}
    assert result.loc["b", "cumulative_share"] == pytest.approx(0.80)
    assert result.loc["f", "cumulative_share"] == pytest.approx(1.0)


def test_abc_configurable_thresholds():
    values = pd.Series({"a": 50, "b": 30, "c": 20})
    # cumulative share before: a 0%, b 50%, c 80%
    assert abc_classify(values, 0.50, 0.90)["abc_class"].tolist() == ["A", "B", "B"]
    assert abc_classify(values, 0.50, 0.75)["abc_class"].tolist() == ["A", "B", "C"]


def test_abc_item_crossing_threshold_is_a():
    values = pd.Series({"big": 95, "small": 5})
    assert abc_classify(values)["abc_class"].tolist() == ["A", "C"]


def test_abc_zero_value_products_are_c():
    values = pd.Series({"a": 100, "zero": 0, "missing": None})
    result = abc_classify(values)
    assert result.loc["zero", "abc_class"] == "C"
    assert result.loc["missing", "abc_class"] == "C"


def test_abc_all_zero_values():
    result = abc_classify(pd.Series({"a": 0, "b": 0}))
    assert set(result["abc_class"]) == {"C"}


def test_abc_ties_are_ordered_by_sku():
    result = abc_classify(pd.Series({"b": 10, "a": 10}))
    assert result.loc["a", "abc_rank"] == 1


def test_xyz_classes_and_boundaries():
    classes = xyz_classify(mean=[1, 1, 1, 1, 1, 0, 1], cv=[0.3, 0.5, 0.8, 1.0, 1.5, math.nan, 0.2],
                           history_days=[60, 60, 60, 60, 60, 60, 10])
    assert classes.tolist() == ["X", "X", "Y", "Y", "Z", NO_DEMAND, INSUFFICIENT]


def _sales(rows):
    return pd.DataFrame(rows, columns=["sku_id", "sale_date", "quantity_sold"]).assign(
        sale_date=lambda d: pd.to_datetime(d["sale_date"]))


SALES = _sales([("A", "2026-01-01", 2), ("A", "2026-01-03", 4), ("A", "2026-01-04", 2),
                ("C", "2026-01-02", 1)])


def test_demand_statistics_missing_days_as_zero():
    stats, window = demand_statistics(SALES, pd.Series(["A", "B", "C"]),
                                      AnalysisSettings(missing_days_as_zero=True))
    a = stats.set_index("sku_id").loc["A"]
    assert window.days == 4
    assert a["avg_daily_demand"] == pytest.approx(2.0)            # 8 / 4 days
    assert a["demand_variance"] == pytest.approx(8 / 3)           # sample variance of 2,0,4,2
    assert a["days_with_sales"] == 3
    b = stats.set_index("sku_id").loc["B"]                        # no sales at all
    assert b["avg_daily_demand"] == 0 and b["std_daily_demand"] == 0
    assert math.isnan(b["cv"])


def test_demand_statistics_observed_days_only():
    stats, _ = demand_statistics(SALES, pd.Series(["A"]), AnalysisSettings(missing_days_as_zero=False))
    a = stats.set_index("sku_id").loc["A"]
    assert a["avg_daily_demand"] == pytest.approx(8 / 3)          # mean of 2,4,2
    assert a["demand_variance"] == pytest.approx(4 / 3)


def test_zero_variance_demand():
    sales = _sales([("A", f"2026-01-0{d}", 5) for d in range(1, 8)])
    stats, _ = demand_statistics(sales, pd.Series(["A"]), AnalysisSettings())
    assert stats.loc[0, "std_daily_demand"] == 0
    assert stats.loc[0, "cv"] == 0


def test_analysis_window_limits_history():
    stats, window = demand_statistics(SALES, pd.Series(["A"]), AnalysisSettings(analysis_days=2))
    assert window.days == 2 and str(window.start.date()) == "2026-01-03"
    assert stats.loc[0, "total_qty"] == 6
    assert window.annualisation_factor == pytest.approx(365 / 2)


def test_empty_sales():
    empty = _sales([])
    stats, window = demand_statistics(empty, pd.Series(["A"]), AnalysisSettings())
    assert window is None
    assert math.isnan(stats.loc[0, "avg_daily_demand"])
