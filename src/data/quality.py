"""Data-quality report and exploratory profile of the loaded files."""
import pandas as pd

from src.data.schema import FILE_SPECS


def quality_summary(validation) -> pd.DataFrame:
    """One row per supplied file: records, valid, excluded, duplicates, missing values."""
    rows = []
    for key, result in validation.files.items():
        spec = FILE_SPECS[key]
        unique_skus = None
        if result.clean is not None and "sku_id" in result.clean:
            unique_skus = result.clean["sku_id"].nunique()
        rows.append({
            "file": spec.label,
            "status": "Blocked" if result.file_errors else "Loaded",
            "total_records": result.total_rows,
            "valid_records": result.valid_rows,
            "excluded_records": result.excluded_rows,
            "duplicate_records": result.duplicate_rows,
            "missing_values": sum(result.missing_values.values()),
            "unique_skus": unique_skus,
            "ignored_columns": ", ".join(result.ignored_columns),
        })
    return pd.DataFrame(rows)


def missing_values_table(validation) -> pd.DataFrame:
    """Missing values per column, with whether the column is mandatory."""
    rows = []
    for key, result in validation.files.items():
        spec = FILE_SPECS[key]
        for col, count in result.missing_values.items():
            rows.append({"file": spec.label, "column": col,
                         "mandatory": spec.column(col).required, "missing_values": count,
                         "missing_pct": count / result.total_rows if result.total_rows else 0})
    return pd.DataFrame(rows, columns=["file", "column", "mandatory", "missing_values",
                                       "missing_pct"])


def column_profile(frame: pd.DataFrame) -> pd.DataFrame:
    """Structure of a clean frame: data type, non-null count, distinct values, min/max."""
    rows = []
    for col in frame.columns:
        s = frame[col]
        numeric_or_date = pd.api.types.is_numeric_dtype(s) or pd.api.types.is_datetime64_any_dtype(s)
        rows.append({
            "column": col, "dtype": str(s.dtype), "non_null": int(s.notna().sum()),
            "distinct": int(s.nunique()),
            "min": s.min() if numeric_or_date and s.notna().any() else None,
            "max": s.max() if numeric_or_date and s.notna().any() else None,
        })
    return pd.DataFrame(rows).astype({"min": str, "max": str})
