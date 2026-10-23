"""Validation of input files.

Rules
-----
* File-level errors (empty file, missing required columns, unreadable CSV) block the
  analysis: nothing is guessed.
* Row-level **errors** (bad number, invalid date, negative stock, ...) exclude that
  row. Every excluded row is listed with the reason and how to fix it.
* Row-level **warnings** keep the row but are reported (e.g. price below cost).
* Nothing is dropped silently: the quality report lists every exclusion.
"""
import math
from dataclasses import dataclass, field

import pandas as pd

from src.data.schema import (FILE_SPECS, INCOMING_PO_STATUSES, FileSpec,
                             normalise_status)

MISSING_TOKENS = {"", "na", "n/a", "nan", "null", "none", "-"}
ISSUE_COLUMNS = ["file", "row_number", "column", "value", "severity", "problem", "how_to_fix"]
# Show at most this many issues of the same type per column (the counts stay exact).
MAX_ISSUES_PER_RULE = 200


@dataclass
class FileValidation:
    key: str
    label: str
    file_errors: list[str] = field(default_factory=list)
    issues: list[dict] = field(default_factory=list)
    issue_counts: dict[tuple, int] = field(default_factory=dict)
    clean: pd.DataFrame | None = None       # typed, valid rows (warnings kept)
    total_rows: int = 0
    duplicate_rows: int = 0
    missing_values: dict[str, int] = field(default_factory=dict)
    excluded_mask: pd.Series | None = None   # True = row excluded (aligned to raw rows)
    ignored_columns: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.file_errors

    @property
    def excluded_rows(self) -> int:
        return 0 if self.excluded_mask is None else int(self.excluded_mask.sum())

    @property
    def valid_rows(self) -> int:
        return 0 if self.clean is None else len(self.clean)

    def add_issue(self, rows: pd.Series, column: str, values: pd.Series, severity: str,
                  problem: str, how_to_fix: str) -> None:
        """Record an issue for every row in ``rows`` (index labels of the raw frame)."""
        if len(rows) == 0:
            return
        rule = (column, severity, problem)
        self.issue_counts[rule] = self.issue_counts.get(rule, 0) + len(rows)
        for idx in list(rows)[:MAX_ISSUES_PER_RULE]:
            self.issues.append({
                "file": self.label, "row_number": int(idx) + 2,  # +2: header is row 1
                "column": column, "value": str(values.get(idx, "")), "severity": severity,
                "problem": problem, "how_to_fix": how_to_fix,
            })

    def exclude(self, mask: pd.Series) -> None:
        self.excluded_mask = mask if self.excluded_mask is None else (self.excluded_mask | mask)


@dataclass
class DatasetValidation:
    files: dict[str, FileValidation]
    cross_issues: FileValidation

    @property
    def blocking_errors(self) -> list[str]:
        errors = []
        for spec in FILE_SPECS.values():
            result = self.files.get(spec.key)
            if result is None:
                if spec.required:
                    errors.append(f"{spec.label}: this file is required but was not provided.")
                continue
            errors += [f"{result.label}: {e}" for e in result.file_errors]
        products = self.files.get("products")
        if products is not None and products.ok and products.valid_rows == 0:
            errors.append("Products & Inventory: no valid product rows remain after validation.")
        return errors

    @property
    def is_usable(self) -> bool:
        return not self.blocking_errors

    @property
    def excluded_total(self) -> int:
        return sum(f.excluded_rows for f in self.files.values())

    def issues_frame(self) -> pd.DataFrame:
        rows = [i for f in self.files.values() for i in f.issues] + self.cross_issues.issues
        return pd.DataFrame(rows, columns=ISSUE_COLUMNS)

    def issue_summary(self) -> pd.DataFrame:
        """Exact counts per (file, column, severity, problem)."""
        rows = []
        for f in list(self.files.values()) + [self.cross_issues]:
            for (column, severity, problem), count in f.issue_counts.items():
                rows.append({"file": f.label, "column": column, "severity": severity,
                             "problem": problem, "rows_affected": count})
        return pd.DataFrame(rows, columns=["file", "column", "severity", "problem",
                                           "rows_affected"])


def _strip_text(series: pd.Series) -> pd.Series:
    """Object series with surrounding whitespace removed; missing stays NaN."""
    series = series.astype(object)
    filled = series.notna()
    series[filled] = series[filled].astype(str).str.strip()
    return series


def _is_missing(series: pd.Series) -> pd.Series:
    missing = series.isna().to_numpy().copy()
    missing[~missing] = series[~missing].str.lower().isin(MISSING_TOKENS).to_numpy()
    return pd.Series(missing, index=series.index)


def validate_file(raw: pd.DataFrame | None, spec: FileSpec,
                  read_error: str | None = None) -> FileValidation:
    """Validate one raw file (all columns as text) against its schema."""
    result = FileValidation(spec.key, spec.label)
    if read_error:
        result.file_errors.append(read_error)
        return result
    if raw is None or raw.shape[1] == 0:
        result.file_errors.append("The file is empty. Add a header row and data rows.")
        return result
    result.total_rows = len(raw)
    missing_cols = [c for c in spec.required_columns if c not in raw.columns]
    if missing_cols:
        result.file_errors.append(
            f"Missing required column(s): {', '.join(missing_cols)}. "
            f"Columns found: {', '.join(map(str, raw.columns))}. "
            "Download the template on the Home page to see the expected header.")
    if raw.columns.duplicated().any():
        dup = sorted(set(raw.columns[raw.columns.duplicated()]))
        result.file_errors.append(f"Duplicate column name(s): {', '.join(dup)}.")
    if len(raw) == 0:
        result.file_errors.append("The file has a header but no data rows.")
    if result.file_errors:
        return result

    result.ignored_columns = [c for c in raw.columns if c not in spec.column_names]
    text = raw.reindex(columns=spec.column_names).apply(_strip_text)
    missing = text.apply(_is_missing)
    result.missing_values = {c: int(missing[c].sum()) for c in spec.column_names
                             if c in raw.columns}
    text = text.mask(missing)
    typed = pd.DataFrame(index=text.index)
    result.excluded_mask = pd.Series(False, index=text.index)

    for col in spec.columns:
        values = text[col.name]
        if col.required:
            rows = values.index[values.isna()]
            result.add_issue(rows, col.name, values, "error", "Required value is missing.",
                             f"Fill in '{col.name}' (example: {col.example}).")
            result.exclude(values.isna())

        if col.dtype == "number":
            numbers = pd.to_numeric(values, errors="coerce")
            bad = values.notna() & numbers.isna()
            # pd.to_numeric accepts 'inf', '-inf' and values like '1e400' as valid
            # floats; treat them as non-numeric so they never reach KPI aggregations.
            infinite = numbers.apply(lambda x: math.isinf(x) if pd.notna(x) else False)
            bad = bad | infinite
            result.add_issue(values.index[bad], col.name, values, "error",
                             "Not a valid number.",
                             "Use digits only, with '.' as decimal separator and no "
                             "currency symbols or thousands separators.")
            result.exclude(bad)
            if col.min_value is not None:
                low = (numbers <= col.min_value) if col.strictly_positive else (numbers < col.min_value)
                low = low.fillna(False)
                rule = "greater than" if col.strictly_positive else "at least"
                result.add_issue(values.index[low], col.name, values, "error",
                                 f"Value must be {rule} {col.min_value:g}.",
                                 f"Correct the value of '{col.name}'. Negative or zero "
                                 "quantities and prices are not valid here.")
                result.exclude(low)
            if col.max_value is not None:
                high = (numbers > col.max_value).fillna(False)
                result.add_issue(values.index[high], col.name, values, "error",
                                 f"Value must not exceed {col.max_value:g}.",
                                 f"Check the units of '{col.name}' (days expected).")
                result.exclude(high)
            typed[col.name] = numbers.astype(float)
        elif col.dtype == "date":
            dates = pd.to_datetime(values, errors="coerce", format="ISO8601")
            bad = values.notna() & dates.isna()
            result.add_issue(values.index[bad], col.name, values, "error",
                             "Invalid date.", "Use the format YYYY-MM-DD, e.g. 2026-09-30.")
            result.exclude(bad)
            typed[col.name] = dates.dt.normalize()
        else:
            if col.allowed:
                normalised = values.map(normalise_status, na_action="ignore")
                bad = normalised.notna() & ~normalised.isin(col.allowed)
                result.add_issue(values.index[bad], col.name, values, "error",
                                 "Value not recognised.",
                                 f"Use one of: {', '.join(col.allowed)}.")
                result.exclude(bad)
                values = normalised
            typed[col.name] = values.astype(object).where(values.notna(), None)

    # Exact duplicate rows: keep the first, exclude the rest.
    exact_dup = text.duplicated(keep="first")
    result.duplicate_rows = int(exact_dup.sum())
    result.add_issue(text.index[exact_dup], "(entire row)", pd.Series(dtype=str), "error",
                     "Exact duplicate of an earlier row - excluded.",
                     "Remove repeated rows from the file if they are not real "
                     "separate transactions.")
    result.exclude(exact_dup)

    # Conflicting duplicate keys (same ID, different content): ambiguous, exclude all.
    # After removing exact duplicates, any repeated key has conflicting content.
    if spec.key_columns:
        key_cols = list(spec.key_columns)
        remaining = text[~exact_dup]
        conflict = (remaining.duplicated(subset=key_cols, keep=False)
                    & remaining[key_cols].notna().all(axis=1))
        conflict = conflict.reindex(text.index, fill_value=False)
        label = " + ".join(key_cols)
        result.add_issue(text.index[conflict], label,
                         text[key_cols].astype(str).agg(" | ".join, axis=1), "error",
                         f"Duplicate {label} with different values - all copies excluded.",
                         f"Each {label} must appear only once. Merge or correct the rows.")
        result.exclude(conflict)

    result.clean = typed[~result.excluded_mask].copy()
    _file_specific_rules(result, spec)
    return result


def _file_specific_rules(result: FileValidation, spec: FileSpec) -> None:
    """Business rules that involve more than one column of the same file."""
    df = result.clean
    if spec.key == "products":
        loss = df.index[df["selling_price"] < df["unit_cost"]]
        result.add_issue(loss, "selling_price", df["selling_price"], "warning",
                         "Selling price is below unit cost.",
                         "Check the price and cost. The row is kept.")
        over = df.index[df["reserved_qty"].fillna(0) > df["on_hand_qty"]]
        result.add_issue(over, "reserved_qty", df["reserved_qty"], "warning",
                         "Reserved quantity exceeds on-hand stock (backorder).",
                         "Available stock will be negative for this SKU. The row is kept.")
    elif spec.key == "purchase_orders":
        rules = [
            (df["expected_delivery_date"] < df["order_date"], "expected_delivery_date",
             "Expected delivery is before the order date."),
            (df["actual_delivery_date"] < df["order_date"], "actual_delivery_date",
             "Actual delivery is before the order date."),
        ]
        bad_total = pd.Series(False, index=df.index)
        for mask, col, problem in rules:
            mask = mask.fillna(False)
            result.add_issue(df.index[mask], col, df[col].astype(str), "error", problem,
                             "Correct the dates (YYYY-MM-DD).")
            bad_total |= mask
        result.exclude(bad_total.reindex(result.excluded_mask.index, fill_value=False))
        df = df[~bad_total]
        received_no_date = df.index[(df["status"] == "received") & df["actual_delivery_date"].isna()]
        result.add_issue(received_no_date, "actual_delivery_date", df["status"], "warning",
                         "Received order has no actual delivery date.",
                         "Add the delivery date to use it as a lead-time observation.")
        open_with_date = df.index[df["status"].isin(INCOMING_PO_STATUSES)
                                  & df["actual_delivery_date"].notna()]
        result.add_issue(open_with_date, "status", df["status"], "warning",
                         "Order is open/in transit but already has an actual delivery date.",
                         "Update the status. This order is NOT counted as incoming stock.")
        result.clean = df
    elif spec.key == "suppliers":
        pass  # all supplier rules are expressed in the schema


def validate_references(files: dict[str, FileValidation]) -> FileValidation:
    """Cross-file checks: every key must refer to a record that exists."""
    cross = FileValidation("references", "Cross-file references")
    products, sales = files.get("products"), files.get("sales")
    suppliers, pos = files.get("suppliers"), files.get("purchase_orders")
    if not (products and products.ok):
        return cross
    sku_ids = set(products.clean["sku_id"])

    if suppliers and suppliers.ok:
        known = set(suppliers.clean["supplier_id"])
        p = products.clean
        unknown = p.index[~p["supplier_id"].isin(known)]
        cross.add_issue(unknown, "supplier_id (Products)", p["supplier_id"], "warning",
                        "Supplier not found in the suppliers file.",
                        "Add the supplier to the suppliers file. Until then the SKU "
                        "has no lead time and is marked 'Insufficient Data'.")

    for result, label in ((sales, "Sales History"), (pos, "Purchase Orders")):
        if not (result and result.ok):
            continue
        df = result.clean
        orphan = ~df["sku_id"].isin(sku_ids)
        result.add_issue(df.index[orphan], "sku_id", df["sku_id"], "error",
                         "SKU not found in the products file - row excluded.",
                         "Add the SKU to the products file or correct the SKU ID.")
        result.exclude(orphan.reindex(result.excluded_mask.index, fill_value=False))
        result.clean = df[~orphan]
    return cross


def validate_dataset(raw_frames: dict[str, pd.DataFrame | None],
                     read_errors: dict[str, str] | None = None) -> DatasetValidation:
    """Validate all supplied files. ``raw_frames`` maps file key -> raw text frame."""
    read_errors = read_errors or {}
    files = {}
    for key, spec in FILE_SPECS.items():
        if key in raw_frames or key in read_errors:
            files[key] = validate_file(raw_frames.get(key), spec, read_errors.get(key))
    cross = validate_references(files)
    return DatasetValidation(files=files, cross_issues=cross)
