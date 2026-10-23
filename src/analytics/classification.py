"""ABC (value) and XYZ (demand variability) classification.

ABC rule
--------
Annual consumption value = annual demand quantity x unit cost. Products are sorted
by value (highest first, ties by SKU ID). A product's class depends on the
cumulative share of value of all products ranked *before* it:

* A: cumulative share before the product < A threshold (default 80%)
* B: cumulative share before the product < B threshold (default 95%)
* C: everything else, including all products with zero consumption value.

Using the share *before* the product means the product that crosses the 80% line
is still A, and there is always at least one A product when any value exists.
The ranking is identical for observed-period and annualised values; only the
reported amounts differ.

XYZ rule
--------
CV = std of daily demand / mean daily demand (see ``demand.py`` for how days
without sales are treated).

* X: CV <= X threshold (0.50)  - stable, predictable demand
* Y: CV <= Y threshold (1.00)  - moderate variability
* Z: CV  > Y threshold         - erratic / intermittent demand
* "No Demand": no units sold in the window (CV undefined, mean = 0)
* "Insufficient Data": less history than ``min_history_days``
"""
import numpy as np
import pandas as pd

from src.config import AnalysisSettings

ABC_CLASSES = ("A", "B", "C")
XYZ_CLASSES = ("X", "Y", "Z")
NO_DEMAND = "No Demand"
INSUFFICIENT = "Insufficient Data"

ABC_MEANING = {
    "A": "Highest-value products: a small share of SKUs that makes up most of the "
         "consumption value. Review often, keep forecasts and stock accurate.",
    "B": "Medium-value products. Review regularly with standard policies.",
    "C": "Low-value products, often many SKUs with little value. Use simple rules "
         "and avoid spending much management time.",
}
XYZ_MEANING = {
    "X": "Stable demand (CV <= X threshold): easy to plan, low safety stock needed.",
    "Y": "Variable demand (trends or seasonality): needs closer monitoring.",
    "Z": "Erratic or intermittent demand: hard to forecast, needs judgement.",
    NO_DEMAND: "No units sold in the analysis period. Check for obsolete or dead stock.",
    INSUFFICIENT: "Too little sales history to measure variability.",
}

GROUP_RECOMMENDATIONS = {
    "AX": ("Predictable, high value", "Keep lean stock; automate replenishment and review "
           "frequently. Small safety stock is enough."),
    "AY": ("Monitor closely", "High value with variable demand. Review weekly and adjust "
           "for trend/seasonality before ordering."),
    "AZ": ("Needs further review", "High value and erratic. Investigate demand drivers, "
           "consider make-to-order or closer customer collaboration; safety stock is costly."),
    "BX": ("Predictable", "Standard automatic replenishment with periodic review."),
    "BY": ("Monitor", "Regular review; seasonal adjustment of reorder points."),
    "BZ": ("Review", "Erratic medium-value items: check whether stock is needed "
           "or orders can be placed on demand."),
    "CX": ("Low effort", "Stable, low value: order in larger, less frequent batches."),
    "CY": ("Low effort", "Simple rules with a slightly higher buffer."),
    "CZ": ("Rationalise", "Low value and erratic: candidates for range reduction or "
           "order-on-demand."),
}


def abc_classify(values: pd.Series, a_threshold: float = 0.80,
                 b_threshold: float = 0.95) -> pd.DataFrame:
    """ABC class for each item of ``values`` (indexed by SKU).

    Returns a frame with value_share, cumulative_share and abc_class.
    """
    values = values.astype(float).fillna(0.0).clip(lower=0)
    total = values.sum()
    order = values.reset_index()
    order.columns = ["sku_id", "value"]
    order = order.sort_values(["value", "sku_id"], ascending=[False, True], kind="stable")
    if total > 0:
        share = order["value"] / total
        cum_after = share.cumsum()
        cum_before = cum_after - share
    else:
        share = cum_after = cum_before = pd.Series(0.0, index=order.index)
    cls = np.where(order["value"] <= 0, "C",
                   np.where(cum_before < a_threshold - 1e-12, "A",
                            np.where(cum_before < b_threshold - 1e-12, "B", "C")))
    order["value_share"] = share
    order["cumulative_share"] = cum_after
    order["abc_rank"] = np.arange(1, len(order) + 1)
    order["abc_class"] = cls
    return order.set_index("sku_id").reindex(values.index)


def xyz_classify(mean, cv, history_days, x_threshold: float = 0.50,
                 y_threshold: float = 1.00, min_history_days: int = 28) -> np.ndarray:
    """XYZ class from mean daily demand, CV and the number of history days."""
    mean = np.asarray(mean, dtype=float)
    cv = np.asarray(cv, dtype=float)
    history = np.asarray(history_days, dtype=float)
    return np.select(
        [history < min_history_days, ~(mean > 0), cv <= x_threshold, cv <= y_threshold],
        [INSUFFICIENT, NO_DEMAND, "X", "Y"],
        default="Z",
    )


def classify_products(products: pd.DataFrame, demand: pd.DataFrame, window,
                      settings: AnalysisSettings) -> pd.DataFrame:
    """Combine product data, demand statistics, ABC and XYZ into one table."""
    df = products.merge(demand, on="sku_id", how="left")
    df["observed_consumption_value"] = df["total_qty"].fillna(0) * df["unit_cost"]
    factor = window.annualisation_factor if window else np.nan
    df["annual_consumption_value"] = df["observed_consumption_value"] * factor
    abc = abc_classify(df.set_index("sku_id")["annual_consumption_value"],
                       settings.abc_a_threshold, settings.abc_b_threshold)
    df = df.join(abc[["value_share", "cumulative_share", "abc_rank", "abc_class"]], on="sku_id")
    if window is None:
        df["abc_class"] = INSUFFICIENT
    df["abc_note"] = np.where(df["observed_consumption_value"] <= 0,
                              "No consumption in period", "")
    df["xyz_class"] = xyz_classify(df["avg_daily_demand"], df["cv"], df["history_days"].fillna(0),
                                   settings.xyz_x_threshold, settings.xyz_y_threshold,
                                   settings.min_history_days)
    df["abc_xyz"] = np.where(df["xyz_class"].isin(XYZ_CLASSES) & df["abc_class"].isin(ABC_CLASSES),
                             df["abc_class"] + df["xyz_class"],
                             df["abc_class"] + " / " + df["xyz_class"])
    df["group_focus"] = df["abc_xyz"].map(lambda g: GROUP_RECOMMENDATIONS.get(g, ("", ""))[0])
    df["recommendation"] = df["abc_xyz"].map(lambda g: GROUP_RECOMMENDATIONS.get(g, ("", ""))[1])
    no_group = df["recommendation"] == ""
    df.loc[no_group & (df["xyz_class"] == NO_DEMAND), "recommendation"] = (
        "No sales in the period: review for obsolescence, markdown or return to supplier.")
    df.loc[no_group & (df["xyz_class"] == INSUFFICIENT), "recommendation"] = (
        "Collect more sales history before setting automatic stock policies.")
    df.loc[no_group, "group_focus"] = np.where(df.loc[no_group, "xyz_class"] == NO_DEMAND,
                                               "Review stock", "Insufficient data")
    return df


def abc_summary(classified: pd.DataFrame) -> pd.DataFrame:
    """Counts, consumption value and inventory value per ABC class."""
    df = classified.assign(inventory_value=classified["on_hand_qty"] * classified["unit_cost"])
    out = (df.groupby("abc_class")
           .agg(products=("sku_id", "count"),
                annual_consumption_value=("annual_consumption_value", "sum"),
                inventory_value=("inventory_value", "sum"))
           .reindex([c for c in ABC_CLASSES if c in df["abc_class"].unique()]))
    out["share_of_products"] = out["products"] / out["products"].sum()
    total_value = out["annual_consumption_value"].sum()
    out["share_of_consumption_value"] = (out["annual_consumption_value"] / total_value
                                         if total_value > 0 else 0.0)
    total_inv = out["inventory_value"].sum()
    out["share_of_inventory_value"] = out["inventory_value"] / total_inv if total_inv > 0 else 0.0
    return out.reset_index()


def xyz_summary(classified: pd.DataFrame) -> pd.DataFrame:
    df = classified.assign(inventory_value=classified["on_hand_qty"] * classified["unit_cost"])
    order = [c for c in XYZ_CLASSES + (NO_DEMAND, INSUFFICIENT) if c in df["xyz_class"].unique()]
    out = (df.groupby("xyz_class")
           .agg(products=("sku_id", "count"), inventory_value=("inventory_value", "sum"),
                median_cv=("cv", "median"))
           .reindex(order))
    out["share_of_products"] = out["products"] / out["products"].sum()
    return out.reset_index()


def abc_xyz_matrix(classified: pd.DataFrame, value: str = "products") -> pd.DataFrame:
    """3x3 matrix (rows A/B/C, columns X/Y/Z) of product counts or inventory value."""
    df = classified[classified["abc_class"].isin(ABC_CLASSES)
                    & classified["xyz_class"].isin(XYZ_CLASSES)]
    df = df.assign(inventory_value=df["on_hand_qty"] * df["unit_cost"])
    if value == "products":
        table = df.pivot_table(index="abc_class", columns="xyz_class", values="sku_id",
                               aggfunc="count", fill_value=0)
    else:
        table = df.pivot_table(index="abc_class", columns="xyz_class", values=value,
                               aggfunc="sum", fill_value=0)
    return table.reindex(index=list(ABC_CLASSES), columns=list(XYZ_CLASSES), fill_value=0)
