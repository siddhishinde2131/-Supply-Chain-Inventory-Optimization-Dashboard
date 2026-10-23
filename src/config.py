"""Central configuration: file paths, default analysis settings and service levels.

Every business threshold used by the dashboard lives in ``AnalysisSettings`` so it
is documented in one place and can be changed from the Home page.
"""
from dataclasses import dataclass, fields
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
SAMPLE_DIR = DATA_DIR / "sample"
SQL_DIR = PROJECT_ROOT / "sql"

# Default service-level -> Z-score mappings required by the project brief.
# Any other service level is converted with the inverse normal distribution.
SERVICE_LEVEL_Z = {0.90: 1.282, 0.95: 1.645, 0.99: 2.326}
SCENARIO_SERVICE_LEVELS = (0.90, 0.95, 0.99)

DAYS_PER_YEAR = 365


@dataclass(frozen=True)
class AnalysisSettings:
    """All configurable assumptions of the analysis (frozen so it can be a cache key)."""

    service_level: float = 0.95          # target cycle service level for safety stock
    analysis_days: int = 365             # length of the demand history window (days)
    abc_a_threshold: float = 0.80        # A = items making up the first 80% of value
    abc_b_threshold: float = 0.95        # B = next 15% (cumulative 95%), C = rest
    xyz_x_threshold: float = 0.50        # X: CV <= 0.50
    xyz_y_threshold: float = 1.00        # Y: 0.50 < CV <= 1.00, Z: CV > 1.00
    holding_cost_rate: float = 0.25      # annual holding cost as share of inventory value
    target_coverage_days: int = 30       # order-up-to level = ROP + this many days of demand
    excess_buffer_days: int = 60         # stock above target level + this many days = excess
    min_history_days: int = 28           # minimum demand history to calculate variability
    missing_days_as_zero: bool = True    # dates with no sales record = zero demand
    use_lead_time_variability: bool = True  # False forces the fixed-lead-time model
    min_lead_time_observations: int = 3  # received POs needed to estimate lead-time std
    currency_symbol: str = "$"

    def validate(self) -> list[str]:
        """Return a list of problems with the settings (empty list = valid)."""
        problems = []
        if not 0.5 <= self.service_level < 1:
            problems.append("Service level must be between 50% and 99.9%.")
        if not 0 < self.abc_a_threshold < self.abc_b_threshold < 1:
            problems.append("ABC thresholds must satisfy 0 < A < B < 100%.")
        if not 0 < self.xyz_x_threshold < self.xyz_y_threshold:
            problems.append("XYZ thresholds must satisfy 0 < X < Y.")
        if self.analysis_days < 7:
            problems.append("Analysis period must be at least 7 days.")
        if self.holding_cost_rate < 0:
            problems.append("Holding-cost rate cannot be negative.")
        if self.target_coverage_days < 0 or self.excess_buffer_days < 0:
            problems.append("Coverage and excess buffer days cannot be negative.")
        if self.min_history_days < 2:
            problems.append("Minimum history must be at least 2 days.")
        return problems


def settings_as_rows(settings: AnalysisSettings) -> list[dict]:
    """Settings as a list of {setting, value} rows for display and reports."""
    return [{"setting": f.name, "value": getattr(settings, f.name)} for f in fields(settings)]
