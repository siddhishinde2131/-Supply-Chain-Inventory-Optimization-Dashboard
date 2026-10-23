"""CSV reading and validation rules."""
from src.data.loader import read_csv_bytes
from src.data.schema import FILE_SPECS
from src.validation.validator import validate_file
from tests.helpers import build, csv

PRODUCTS_HEADER = "sku_id,product_name,category,unit_cost,selling_price,on_hand_qty,supplier_id,snapshot_date"
SUPPLIERS = "supplier_id,supplier_name,avg_lead_time_days\nS1,Supplier One,5"


def validate(key: str, text: str):
    frame, error = read_csv_bytes(csv(text) if text else b"")
    return validate_file(frame, FILE_SPECS[key], error)


def problems(result) -> set[str]:
    return {i["problem"] for i in result.issues}


def test_empty_file_is_rejected():
    result = validate("products", "")
    assert not result.ok and "empty" in result.file_errors[0]


def test_header_only_file_is_rejected():
    result = validate("products", PRODUCTS_HEADER)
    assert not result.ok and "no data rows" in result.file_errors[0]


def test_missing_required_column():
    result = validate("suppliers", "supplier_id,supplier_name\nS1,One")
    assert not result.ok
    assert "avg_lead_time_days" in result.file_errors[0]


def test_semicolon_csv_gives_clear_message():
    frame, error = read_csv_bytes(b"sku_id;product_name\nA;B\n")
    assert frame is None and "';'" in error


def test_column_aliases_and_whitespace_are_normalised():
    frame, _ = read_csv_bytes(b" SKU ,Product Name,Qty\nA,B,1\n")
    assert list(frame.columns) == ["sku_id", "product_name", "quantity_sold"]


def test_invalid_numbers_dates_and_negative_values_are_excluded():
    result = validate("products", f"""{PRODUCTS_HEADER}
        A,Good,Cat,10,20,5,S1,2026-01-31
        B,BadCost,Cat,abc,20,5,S1,2026-01-31
        C,ZeroCost,Cat,0,20,5,S1,2026-01-31
        D,NegStock,Cat,10,20,-1,S1,2026-01-31
        E,BadDate,Cat,10,20,5,S1,31/01/2026
        F,NoName,,10,20,5,S1,2026-01-31
        G,NegPrice,Cat,10,-2,5,S1,2026-01-31""")
    assert result.ok
    assert result.clean["sku_id"].tolist() == ["A"]
    assert result.excluded_rows == 6
    found = problems(result)
    assert {"Not a valid number.", "Value must be greater than 0.", "Value must be at least 0.",
            "Invalid date.", "Required value is missing."} <= found
    rows = {i["row_number"] for i in result.issues}
    assert rows == {3, 4, 5, 6, 7, 8}       # CSV line numbers (header = line 1)


def test_infinite_numbers_are_rejected_as_not_valid():
    """inf, -inf and 1e400 must be caught even though pd.to_numeric accepts them."""
    result = validate("products", f"""{PRODUCTS_HEADER}
        A,Good,Cat,10,20,5,S1,2026-01-31
        B,Inf,Cat,inf,20,5,S1,2026-01-31
        C,NegInf,Cat,-inf,20,5,S1,2026-01-31
        D,HugeExp,Cat,1e400,20,5,S1,2026-01-31""")
    assert result.ok
    assert result.clean["sku_id"].tolist() == ["A"]
    assert result.excluded_rows == 3
    assert "Not a valid number." in problems(result)


def test_conflicting_duplicate_ids_are_all_excluded_but_exact_duplicates_keep_one():
    result = validate("products", f"""{PRODUCTS_HEADER}
        A,One,Cat,10,20,5,S1,2026-01-31
        A,Two,Cat,10,20,5,S1,2026-01-31
        B,Same,Cat,10,20,5,S1,2026-01-31
        B,Same,Cat,10,20,5,S1,2026-01-31""")
    assert result.clean["sku_id"].tolist() == ["B"]
    assert result.duplicate_rows == 1


def test_invalid_lead_times():
    result = validate("suppliers", """supplier_id,supplier_name,avg_lead_time_days,lead_time_std_days
        S1,Ok,5,1
        S2,Zero,0,
        S3,TooLong,400,
        S4,NegStd,5,-1""")
    assert result.clean["supplier_id"].tolist() == ["S1"]


def test_warnings_keep_rows():
    result = validate("products", f"""{PRODUCTS_HEADER},reserved_qty
        A,Loss,Cat,30,20,5,S1,2026-01-31,10""")
    assert result.clean["sku_id"].tolist() == ["A"]
    severities = {i["severity"] for i in result.issues}
    assert severities == {"warning"}


def test_purchase_order_rules():
    result = validate("purchase_orders", """po_id,sku_id,order_qty,order_date,expected_delivery_date,actual_delivery_date,status
        P1,A,10,2026-01-01,2026-01-10,,Open
        P2,A,10,2026-01-01,2026-01-10,,shipped
        P3,A,10,2026-01-10,2026-01-01,,open
        P4,A,0,2026-01-01,2026-01-10,,open
        P5,A,10,2026-01-01,2026-01-10,,In Transit""")
    assert result.clean["po_id"].tolist() == ["P1", "P5"]
    assert result.clean["status"].tolist() == ["open", "in_transit"]


def test_reference_checks_across_files():
    dataset, validation = build(
        f"""{PRODUCTS_HEADER}
        A,One,Cat,10,20,5,S1,2026-01-31
        B,Two,Cat,10,20,5,S9,2026-01-31""",
        "2026-01-01,A,3\n2026-01-01,ZZZ,4",
        SUPPLIERS)
    assert dataset is not None
    assert len(dataset.sales) == 1                    # orphan SKU sale excluded
    cross = {i["problem"] for i in validation.cross_issues.issues}
    assert "Supplier not found in the suppliers file." in cross
    assert len(dataset.products) == 2                 # product kept, flagged as warning


def test_missing_required_file_blocks_analysis():
    from src.data.loader import dataset_from_sources

    dataset, validation = dataset_from_sources({"products": csv(f"{PRODUCTS_HEADER}\nA,One,Cat,10,20,5,S1,2026-01-31")},
                                               "x", "upload_csv")
    assert dataset is None
    assert any("required but was not provided" in e for e in validation.blocking_errors)


def test_no_valid_products_blocks_analysis():
    dataset, validation = build(f"{PRODUCTS_HEADER}\nA,One,Cat,-1,20,5,S1,2026-01-31",
                                "2026-01-01,A,3", SUPPLIERS)
    assert dataset is None
    assert any("no valid product rows" in e for e in validation.blocking_errors)


def test_optional_reserved_qty_defaults_to_zero_with_note():
    dataset, _ = build(f"{PRODUCTS_HEADER}\nA,One,Cat,10,20,5,S1,2026-01-31", "2026-01-01,A,3",
                       SUPPLIERS)
    assert dataset.products["reserved_qty"].tolist() == [0.0]
    assert any("reserved" in n for n in dataset.notes)


def test_sales_rows_same_day_are_summed():
    dataset, _ = build(f"{PRODUCTS_HEADER}\nA,One,Cat,10,20,5,S1,2026-01-31",
                       "2026-01-01,A,3\n2026-01-01,A,4\n2026-01-01,A,-2", SUPPLIERS)
    assert dataset.sales["quantity_sold"].tolist() == [7.0]
    assert dataset.validation.excluded_total == 1     # negative row excluded and reported


def test_sample_dataset_meets_requirements(sample_dataset):
    assert sample_dataset.products["sku_id"].nunique() >= 2000
    assert sample_dataset.is_synthetic
    assert sample_dataset.has_purchase_orders
    # deliberately injected problems are detected
    assert sample_dataset.validation.files["sales"].duplicate_rows == 30
