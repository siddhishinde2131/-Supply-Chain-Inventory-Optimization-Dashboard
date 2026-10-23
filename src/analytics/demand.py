"""Demand statistics, trends, seasonality and outlier flags.

Analysis window
---------------
The window ends on the last sales date in the data and covers ``analysis_days``
days (or the whole history if it is shorter).

Dates without a sales record (policy ``missing_days_as_zero``)
--------------------------------------------------------------
* True (default): the sales file is treated as a complete log, so a day inside the
  window without a record for a SKU is *zero demand*. Days on which **no SKU at
  all** sold anything are reported as possible data gaps, so the user can judge
  whether that interpretation is safe.
* False: statistics use only the days that have a record for that SKU (the mean
  then describes "demand on selling days", which overstates average demand).

Mean and standard deviation are computed from sums and sums of squares, which is
the same as building the full SKU x day table but much faster.
"""
from dataclasses import dataclass

import numpy as np
import pandas as pd

from src.config import DAYS_PER_YEAR, AnalysisSettings
from src.inventory.formulas import coefficient_of_variation


@dataclass(frozen=True)
class AnalysisWindow:
    start: pd.Timestamp
    end: pd.Timestamp

    @property
    def days(self) -> int:
        return int((self.end - self.start).days) + 1

    @property
    def annualisation_factor(self) -> float:
        """Multiply observed-period totals by this to estimate annual totals."""
        return DAYS_PER_YEAR / self.days

    @property
    def is_full_year(self) -> bool:
        return self.days >= DAYS_PER_YEAR


def analysis_window(sales: pd.DataFrame, analysis_days: int) -> AnalysisWindow | None:
    if sales.empty:
        return None
    end = sales["sale_date"].max()
    first = sales["sale_date"].min()
    start = max(first, end - pd.Timedelta(days=analysis_days - 1))
    return AnalysisWindow(start=start, end=end)


def sales_in_window(sales: pd.DataFrame, window: AnalysisWindow | None) -> pd.DataFrame:
    if window is None:
        return sales.iloc[0:0]
    mask = sales["sale_date"].between(window.start, window.end)
    return sales[mask]


def demand_statistics(sales: pd.DataFrame, sku_ids: pd.Series,
                      settings: AnalysisSettings) -> tuple[pd.DataFrame, AnalysisWindow | None]:
    """Per-SKU demand statistics over the analysis window.

    Columns: total_qty, days_with_sales, history_days, avg_daily_demand,
    demand_variance (sample, ddof=1), std_daily_demand, cv, annual_demand_estimate.
    """
    window = analysis_window(sales, settings.analysis_days)
    in_window = sales_in_window(sales, window)
    grouped = in_window.groupby("sku_id")["quantity_sold"]
    squares = (in_window["quantity_sold"] ** 2).groupby(in_window["sku_id"])
    stats = pd.DataFrame({
        "total_qty": grouped.sum(),
        "sum_sq": squares.sum(),
        "days_with_sales": in_window[in_window["quantity_sold"] > 0].groupby("sku_id").size(),
        "records": grouped.size(),
    }, dtype=float).reindex(pd.Index(sku_ids, name="sku_id")).fillna(0.0)

    if window is None:
        n = pd.Series(0.0, index=stats.index)
    elif settings.missing_days_as_zero:
        n = pd.Series(float(window.days), index=stats.index)
    else:
        n = stats["records"].astype(float)

    with np.errstate(divide="ignore", invalid="ignore"):
        mean = np.where(n > 0, stats["total_qty"] / n.where(n > 0, 1), np.nan)
        # sample variance: (sum(x^2) - n * mean^2) / (n - 1)
        var = np.where(n > 1, (stats["sum_sq"] - n * np.nan_to_num(mean) ** 2)
                       / (n - 1).where(n > 1, 1), np.nan)
    var = np.clip(var, 0, None)    # remove tiny negative values from rounding
    stats["history_days"] = n
    stats["avg_daily_demand"] = mean
    stats["demand_variance"] = var
    stats["std_daily_demand"] = np.sqrt(var)
    stats["cv"] = coefficient_of_variation(mean, np.sqrt(var))
    factor = window.annualisation_factor if window else np.nan
    stats["annual_demand_estimate"] = stats["total_qty"] * factor
    stats["days_with_sales"] = stats["days_with_sales"].astype(int)
    return stats.drop(columns=["sum_sq", "records"]).reset_index(), window


def data_gap_days(sales: pd.DataFrame, window: AnalysisWindow | None) -> pd.DatetimeIndex:
    """Calendar days inside the window with no sales record for ANY SKU."""
    if window is None:
        return pd.DatetimeIndex([])
    all_days = pd.date_range(window.start, window.end, freq="D")
    recorded = pd.DatetimeIndex(sales_in_window(sales, window)["sale_date"].unique())
    return all_days.difference(recorded)


def flag_outliers(sales: pd.DataFrame, stats: pd.DataFrame, window: AnalysisWindow | None,
                  z_threshold: float = 4.0) -> pd.DataFrame:
    """Sales days far above the SKU's normal level (mean + z * std). Flagged, never removed."""
    in_window = sales_in_window(sales, window)
    if in_window.empty:
        return in_window.assign(threshold=pd.Series(dtype=float))
    ref = stats.set_index("sku_id")[["avg_daily_demand", "std_daily_demand"]]
    merged = in_window.join(ref, on="sku_id")
    merged["threshold"] = merged["avg_daily_demand"] + z_threshold * merged["std_daily_demand"]
    flagged = merged[(merged["std_daily_demand"] > 0) & (merged["quantity_sold"] > merged["threshold"])]
    return flagged[["sku_id", "sale_date", "quantity_sold", "avg_daily_demand", "threshold"]]


def sales_trend(sales: pd.DataFrame, products: pd.DataFrame, freq: str = "MS",
                by: str | None = None) -> pd.DataFrame:
    """Units, cost of goods sold (units x unit cost) and revenue per period."""
    if sales.empty:
        return pd.DataFrame(columns=["period", "units", "cogs", "revenue"])
    cols = ["sku_id", "unit_cost"] + ([by] if by else [])
    df = sales.merge(products[cols], on="sku_id", how="left")
    df["cogs"] = df["quantity_sold"] * df["unit_cost"]
    keys = [pd.Grouper(key="sale_date", freq=freq)] + ([by] if by else [])
    trend = (df.groupby(keys)
             .agg(units=("quantity_sold", "sum"), cogs=("cogs", "sum"),
                  revenue=("revenue", lambda s: s.sum(min_count=1)))
             .reset_index().rename(columns={"sale_date": "period"}))
    return trend


def weekday_seasonality(sales: pd.DataFrame, window: AnalysisWindow | None,
                        min_weeks: int = 8) -> pd.DataFrame | None:
    """Index of average daily units per weekday vs the overall daily average.

    Returns None if there are fewer than ``min_weeks`` weeks of history.
    """
    if window is None or window.days < min_weeks * 7:
        return None
    in_window = sales_in_window(sales, window)
    daily = in_window.groupby("sale_date")["quantity_sold"].sum()
    daily = daily.reindex(pd.date_range(window.start, window.end), fill_value=0)
    by_day = daily.groupby(daily.index.dayofweek).mean()
    names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    return pd.DataFrame({"weekday": [names[i] for i in by_day.index],
                         "avg_units": by_day.values,
                         "index_vs_average": by_day.values / daily.mean()})


def monthly_seasonality(sales: pd.DataFrame, window: AnalysisWindow | None) -> pd.DataFrame | None:
    """Month-of-year index; only meaningful with at least 12 months of history."""
    if window is None or not window.is_full_year:
        return None
    in_window = sales_in_window(sales, window)
    daily = in_window.groupby("sale_date")["quantity_sold"].sum()
    daily = daily.reindex(pd.date_range(window.start, window.end), fill_value=0)
    by_month = daily.groupby(daily.index.month).mean()
    return pd.DataFrame({"month": by_month.index, "avg_daily_units": by_month.values,
                         "index_vs_average": by_month.values / daily.mean()})


def category_growth(sales: pd.DataFrame, products: pd.DataFrame,
                    window: AnalysisWindow | None, days: int = 90) -> pd.DataFrame | None:
    """Units in the last ``days`` vs the ``days`` before, per category."""
    if window is None or window.days < 2 * days:
        return None
    df = sales_in_window(sales, window).merge(products[["sku_id", "category"]], on="sku_id")
    recent_start = window.end - pd.Timedelta(days=days - 1)
    prior_start = recent_start - pd.Timedelta(days=days)
    recent = df[df["sale_date"] >= recent_start].groupby("category")["quantity_sold"].sum()
    prior = df[(df["sale_date"] >= prior_start) & (df["sale_date"] < recent_start)] \
        .groupby("category")["quantity_sold"].sum()
    out = pd.DataFrame({"prior_units": prior, "recent_units": recent}).fillna(0)
    out["change_pct"] = np.where(out["prior_units"] > 0,
                                 out["recent_units"] / out["prior_units"].where(out["prior_units"] > 0, 1) - 1,
                                 np.nan)
    return out.reset_index().sort_values("change_pct", ascending=False)
