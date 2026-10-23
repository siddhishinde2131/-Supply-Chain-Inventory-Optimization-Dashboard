"""Report exports reflect the data they are given."""
from src.analytics.pipeline import run_analysis
from src.config import AnalysisSettings
from src.reporting import exports


def test_filename_is_meaningful():
    name = exports.report_filename("replenishment", "Synthetic sample dataset", "sl95")
    assert name.startswith("replenishment_synthetic_sample_dataset_sl95_") and name.endswith(".csv")


def test_reports_respect_filtered_rows(sample_dataset):
    plan = run_analysis(sample_dataset, AnalysisSettings()).plan
    subset = plan[plan["category"] == "Grocery"]
    for builder in (exports.cleaned_inventory_report, exports.classification_report,
                    exports.replenishment_report):
        report = builder(subset)
        assert len(report) == len(subset)
    risk = exports.stockout_risk_report(subset)
    assert set(risk["sku_id"]) <= set(subset["sku_id"])
    csv_bytes = exports.to_csv_bytes(exports.replenishment_report(subset))
    assert csv_bytes.startswith(b"\xef\xbb\xbfsku_id")


def test_data_quality_report_contains_sections(sample_dataset):
    report = exports.data_quality_report(sample_dataset.validation)
    assert {"1. File summary", "2. Missing values", "3. Issue counts"} <= set(report["section"])
