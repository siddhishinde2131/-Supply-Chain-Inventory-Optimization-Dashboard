"""Reading CSV files (from disk or from Streamlit uploads) into raw text frames.

All values are read as text first so validation can report exactly which value
is wrong instead of pandas guessing types. Uploaded files are only read in
memory; the user's original files are never modified or written anywhere.
"""
import io
from pathlib import Path

import pandas as pd

from src.data.cleaning import Dataset, build_dataset
from src.data.sample_generator import SAMPLE_FILES, ensure_sample_data
from src.data.schema import normalise_column_name
from src.validation.validator import validate_dataset


def read_csv_bytes(data: bytes, file_label: str = "file") -> tuple[pd.DataFrame | None, str | None]:
    """Parse CSV bytes. Returns (frame, None) or (None, friendly error message)."""
    if not data or not data.strip():
        return None, "The file is empty. Add a header row and data rows."
    frame = None
    for encoding in ("utf-8-sig", "latin-1"):
        try:
            frame = pd.read_csv(io.BytesIO(data), dtype=str, keep_default_na=False,
                                na_values=[""], encoding=encoding)
            break
        except UnicodeDecodeError:
            continue
        except pd.errors.EmptyDataError:
            return None, "The file is empty. Add a header row and data rows."
        except pd.errors.ParserError as exc:
            return None, (f"The {file_label} could not be read as CSV ({exc}). Make sure every "
                          "row has the same number of comma-separated values.")
    if frame is None:
        return None, "The file encoding is not supported. Save it as UTF-8 CSV."
    if frame.shape[1] == 1 and ";" in str(frame.columns[0]):
        return None, ("The file seems to use ';' as separator. Save it as a comma-separated "
                      "CSV (in Excel: 'CSV UTF-8 (Comma delimited)').")
    frame.columns = [normalise_column_name(c) for c in frame.columns]
    return frame, None


def read_csv_path(path: Path) -> tuple[pd.DataFrame | None, str | None]:
    return read_csv_bytes(Path(path).read_bytes(), Path(path).name)


def load_raw_files(sources: dict[str, bytes]) -> tuple[dict, dict]:
    """Parse several files. Returns (raw_frames, read_errors) keyed by file key."""
    frames, errors = {}, {}
    for key, data in sources.items():
        frame, error = read_csv_bytes(data, key)
        if error:
            errors[key] = error
        else:
            frames[key] = frame
    return frames, errors


def dataset_from_sources(sources: dict[str, bytes], label: str, source_type: str,
                         is_synthetic: bool = False) -> tuple[Dataset | None, object]:
    """Validate the given files and build a Dataset if they are usable.

    Returns (dataset or None, DatasetValidation).
    """
    frames, errors = load_raw_files(sources)
    return dataset_from_frames(frames, label, source_type, is_synthetic, errors)


def dataset_from_frames(frames: dict, label: str, source_type: str, is_synthetic: bool = False,
                        read_errors: dict | None = None) -> tuple[Dataset | None, object]:
    """Validate raw text frames (from CSV or PostgreSQL) and build a Dataset."""
    validation = validate_dataset(frames, read_errors)
    if not validation.is_usable:
        return None, validation
    return build_dataset(validation, label, source_type, is_synthetic), validation


def load_sample_dataset() -> tuple[Dataset | None, object]:
    """Load the synthetic sample dataset, creating the files on first use."""
    paths = ensure_sample_data()
    sources = {key: Path(paths[key]).read_bytes() for key in SAMPLE_FILES}
    return dataset_from_sources(sources, "Synthetic sample dataset", "sample_csv",
                                is_synthetic=True)
