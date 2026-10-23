"""Core inventory formulas (the single, tested implementation used everywhere).

All functions accept scalars or NumPy/pandas arrays (vectorised).

Units: demand in units per day, lead time in days, variance in the squared units.

Assumptions
-----------
* Daily demand and lead time are independent random variables.
* Demand variance uses the *sample* variance (ddof=1) of the daily demand series;
  lead-time variance is the square of the supplied (or sample) standard deviation.
* Demand during lead time is approximately normally distributed, so the
  safety-stock Z-score corresponds to the probability of not stocking out during a
  replenishment cycle (cycle service level).
"""
from statistics import NormalDist

import numpy as np

from src.config import SERVICE_LEVEL_Z


def z_score(service_level: float) -> float:
    """Z-score for a cycle service level. 90/95/99% use the documented table values."""
    for level, z in SERVICE_LEVEL_Z.items():
        if abs(service_level - level) < 1e-9:
            return z
    if not 0 < service_level < 1:
        raise ValueError("Service level must be between 0 and 1 (e.g. 0.95).")
    return round(NormalDist().inv_cdf(service_level), 3)


def safety_stock(z, avg_daily_demand, demand_variance, avg_lead_time, lead_time_variance=0.0):
    """Safety stock with demand AND lead-time variability.

    SS = Z * sqrt(L * sigma_d^2 + d^2 * sigma_L^2)

    With lead_time_variance = 0 this equals the fixed-lead-time formula
    Z * sigma_d * sqrt(L).
    """
    d = np.asarray(avg_daily_demand, dtype=float)
    var_d = np.asarray(demand_variance, dtype=float)
    lead = np.asarray(avg_lead_time, dtype=float)
    var_l = np.asarray(lead_time_variance, dtype=float)
    if np.any(var_d < 0) or np.any(var_l < 0) or np.any(lead < 0):
        raise ValueError("Variances and lead times cannot be negative.")
    return z * np.sqrt(lead * var_d + d ** 2 * var_l)


def safety_stock_fixed_lead_time(z, demand_std, lead_time):
    """Safety stock when only demand varies: SS = Z * sigma_d * sqrt(L)."""
    std = np.asarray(demand_std, dtype=float)
    lead = np.asarray(lead_time, dtype=float)
    if np.any(std < 0) or np.any(lead < 0):
        raise ValueError("Standard deviation and lead time cannot be negative.")
    return z * std * np.sqrt(lead)


def lead_time_demand(avg_daily_demand, avg_lead_time):
    """Expected demand while waiting for a delivery: d * L."""
    return np.asarray(avg_daily_demand, dtype=float) * np.asarray(avg_lead_time, dtype=float)


def reorder_point(avg_daily_demand, avg_lead_time, safety_stock_units):
    """ROP = (d * L) + SS."""
    return lead_time_demand(avg_daily_demand, avg_lead_time) + np.asarray(safety_stock_units, dtype=float)


def stock_position(on_hand, reserved=0.0, incoming=0.0):
    """Stock position = on-hand - reserved + eligible incoming purchase orders."""
    return (np.asarray(on_hand, dtype=float) - np.asarray(reserved, dtype=float)
            + np.asarray(incoming, dtype=float))


def target_stock_level(reorder_point_units, avg_daily_demand, coverage_days):
    """Order-up-to level = ROP + demand for the target coverage period."""
    return (np.asarray(reorder_point_units, dtype=float)
            + np.asarray(avg_daily_demand, dtype=float) * coverage_days)


def apply_order_constraints(quantity, min_order_qty=None, order_multiple=None):
    """Round a raw order quantity up to respect MOQ and pack size.

    * quantity <= 0 -> 0 (nothing to order).
    * quantity > 0 -> at least the MOQ, then rounded UP to the next order multiple.
    Blank (NaN) MOQ or multiple means no constraint.
    """
    qty = np.ceil(np.round(np.asarray(quantity, dtype=float), 9))
    qty = np.where(qty > 0, qty, 0.0)
    if min_order_qty is not None:
        moq = np.nan_to_num(np.asarray(min_order_qty, dtype=float), nan=0.0)
        qty = np.where(qty > 0, np.maximum(qty, moq), 0.0)
    if order_multiple is not None:
        mult = np.nan_to_num(np.asarray(order_multiple, dtype=float), nan=1.0)
        mult = np.where(mult > 0, mult, 1.0)
        qty = np.where(qty > 0, np.ceil(np.round(qty / mult, 9)) * mult, 0.0)
    return qty


def replenishment_quantity(stock_position_units, reorder_point_units, target_level_units,
                           min_order_qty=None, order_multiple=None):
    """Suggested order: if stock position <= ROP, order up to the target level.

    Raw quantity = target level - stock position, then MOQ / multiples are applied.
    Products above their reorder point get 0.
    """
    position = np.asarray(stock_position_units, dtype=float)
    rop = np.asarray(reorder_point_units, dtype=float)
    target = np.asarray(target_level_units, dtype=float)
    raw = np.where(position <= rop, target - position, 0.0)
    return apply_order_constraints(raw, min_order_qty, order_multiple)


def coefficient_of_variation(mean, std):
    """CV = std / mean; NaN where the mean is zero (CV is undefined)."""
    mean = np.asarray(mean, dtype=float)
    std = np.asarray(std, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(mean > 0, std / np.where(mean > 0, mean, 1.0), np.nan)


def safe_divide(numerator, denominator):
    """numerator / denominator, NaN when the denominator is 0 or missing."""
    num = np.asarray(numerator, dtype=float)
    den = np.asarray(denominator, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        result = np.where(den > 0, num / np.where(den > 0, den, 1.0), np.nan)
    return result if result.ndim else float(result)
