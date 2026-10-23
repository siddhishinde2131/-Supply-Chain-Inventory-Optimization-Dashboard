"""Runs the full analysis for a dataset and settings.

Split in two stages so the dashboard only recomputes what changed:
* ``prepare_analysis`` - demand statistics, ABC/XYZ, lead times, incoming orders.
  Depends on the dataset and the classification settings, not the service level.
* ``run_plan`` - safety stock, reorder points, alerts and KPIs for a service level.
"""
from dataclasses import dataclass, replace

import pandas as pd

from src.analytics.classification import classify_products
from src.analytics.demand import AnalysisWindow, demand_statistics
from src.analytics.kpis import inventory_kpis
from src.config import AnalysisSettings
from src.data.cleaning import Dataset
from src.inventory.planning import build_inventory_plan
from src.inventory.stock import incoming_quantities, supplier_lead_time_parameters


@dataclass
class PreparedAnalysis:
    classified: pd.DataFrame
    window: AnalysisWindow | None
    lead_times: pd.DataFrame
    incoming: pd.DataFrame


@dataclass
class AnalysisResult:
    prepared: PreparedAnalysis
    plan: pd.DataFrame
    kpis: dict
    settings: AnalysisSettings

    @property
    def window(self):
        return self.prepared.window


def preparation_key(settings: AnalysisSettings) -> AnalysisSettings:
    """Settings that do NOT influence stage 1 are normalised so cache keys match."""
    return replace(settings, service_level=0.95, holding_cost_rate=0.0,
                   target_coverage_days=0, excess_buffer_days=0,
                   use_lead_time_variability=True, currency_symbol="")


def prepare_analysis(dataset: Dataset, settings: AnalysisSettings) -> PreparedAnalysis:
    demand, window = demand_statistics(dataset.sales, dataset.products["sku_id"], settings)
    classified = classify_products(dataset.products, demand, window, settings)
    lead_times = supplier_lead_time_parameters(dataset.suppliers, dataset.products,
                                               dataset.purchase_orders,
                                               settings.min_lead_time_observations)
    incoming = incoming_quantities(dataset.purchase_orders)
    return PreparedAnalysis(classified, window, lead_times, incoming)


def run_plan(prepared: PreparedAnalysis, settings: AnalysisSettings) -> AnalysisResult:
    plan = build_inventory_plan(prepared.classified, prepared.lead_times, prepared.incoming,
                                settings)
    kpis = inventory_kpis(plan, prepared.window, settings.holding_cost_rate)
    return AnalysisResult(prepared, plan, kpis, settings)


def run_analysis(dataset: Dataset, settings: AnalysisSettings) -> AnalysisResult:
    return run_plan(prepare_analysis(dataset, settings), settings)
