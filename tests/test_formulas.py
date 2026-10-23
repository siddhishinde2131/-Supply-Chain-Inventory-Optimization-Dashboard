"""Inventory formulas checked against hand-calculated examples."""
import math

import numpy as np
import pytest

from src.inventory import formulas as f


@pytest.mark.parametrize("level, expected", [(0.90, 1.282), (0.95, 1.645), (0.99, 2.326),
                                             (0.975, 1.96)])
def test_z_scores(level, expected):
    assert f.z_score(level) == pytest.approx(expected, abs=1e-3)


def test_z_score_rejects_invalid_level():
    with pytest.raises(ValueError):
        f.z_score(1.5)


def test_safety_stock_demand_and_lead_time_variability():
    # Z=1.645, d=10, sigma_d=2 (var 4), L=9, sigma_L=2 (var 4)
    # sqrt(9*4 + 10^2*4) = sqrt(436) = 20.8806 -> 34.3486
    ss = f.safety_stock(1.645, 10, 4, 9, 4)
    assert ss == pytest.approx(1.645 * math.sqrt(436))
    assert ss == pytest.approx(34.3486, abs=1e-3)


def test_zero_lead_time_variability_equals_fixed_lead_time_model():
    combined = f.safety_stock(1.645, 10, 4, 9, 0)
    fixed = f.safety_stock_fixed_lead_time(1.645, 2, 9)
    assert combined == pytest.approx(fixed)
    assert fixed == pytest.approx(9.87)          # 1.645 * 2 * 3


def test_zero_demand_gives_zero_safety_stock_and_reorder_point():
    ss = f.safety_stock(2.326, 0, 0, 14, 9)
    assert ss == 0
    assert f.reorder_point(0, 14, ss) == 0


def test_zero_demand_variance_and_lead_time_variance():
    ss = f.safety_stock(1.645, 10, 0, 5, 0)
    assert ss == 0
    assert f.reorder_point(10, 5, ss) == 50      # pure lead-time demand


def test_reorder_point():
    assert f.reorder_point(10, 9, 9.87) == pytest.approx(99.87)


def test_higher_service_level_means_more_safety_stock():
    values = [f.safety_stock(f.z_score(sl), 10, 4, 9, 1) for sl in (0.90, 0.95, 0.99)]
    assert values[0] < values[1] < values[2]
    assert values[2] / values[0] == pytest.approx(2.326 / 1.282)


def test_negative_inputs_rejected():
    with pytest.raises(ValueError):
        f.safety_stock(1.645, 10, -1, 5)
    with pytest.raises(ValueError):
        f.safety_stock_fixed_lead_time(1.645, 2, -3)


def test_vectorised_inputs():
    ss = f.safety_stock(1.645, np.array([10, 0]), np.array([4, 0]), np.array([9, 9]))
    assert ss.tolist() == pytest.approx([9.87, 0.0])


def test_stock_position():
    assert f.stock_position(100, 10, 30) == 120
    assert f.stock_position(5, 10, 0) == -5      # backorders make it negative


@pytest.mark.parametrize("qty, moq, mult, expected", [
    (37, np.nan, np.nan, 37), (36.2, np.nan, np.nan, 37), (37, 50, np.nan, 50),
    (37, np.nan, 12, 48), (55, 50, 12, 60), (0, 50, 12, 0), (-5, 50, 12, 0), (48, np.nan, 12, 48),
])
def test_order_constraints(qty, moq, mult, expected):
    assert float(f.apply_order_constraints(qty, moq, mult)) == expected


def test_replenishment_quantity_only_when_at_or_below_reorder_point():
    target = f.target_stock_level(50, 10, 30)          # 50 + 300 = 350
    assert target == 350
    assert f.replenishment_quantity(40, 50, target) == 310
    assert f.replenishment_quantity(50, 50, target) == 300   # exactly at ROP -> order
    assert f.replenishment_quantity(51, 50, target) == 0
    assert f.replenishment_quantity(45, 50, target, 100, 50) == 350  # 305 -> multiple of 50


def test_coefficient_of_variation_and_safe_divide():
    assert f.coefficient_of_variation([2, 0], [1, 0]).tolist()[0] == 0.5
    assert math.isnan(f.coefficient_of_variation([2, 0], [1, 0])[1])
    assert math.isnan(f.safe_divide(5, 0))
    assert f.safe_divide(6, 3) == 2
