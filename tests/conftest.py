"""Shared test fixtures."""
import pytest


@pytest.fixture(scope="session")
def sample_dataset():
    """The synthetic sample dataset (generated on first use, then re-used)."""
    from src.data.loader import load_sample_dataset

    dataset, validation = load_sample_dataset()
    assert dataset is not None, validation.blocking_errors
    return dataset
