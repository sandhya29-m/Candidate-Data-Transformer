"""Unit tests for date normalization."""

from datetime import datetime

import pytest

from candidate_transformer.normalization import DateNormalizer


@pytest.mark.parametrize(
    ("raw_date", "expected"),
    [
        ("2024", "2024"),
        ("2024-06", "2024-06"),
        ("06/2024", "2024-06"),
        ("Jun 2024", "2024-06"),
        ("June 2024", "2024-06"),
        ("2024-06-29", "2024-06-29"),
        ("06/29/2024", "2024-06-29"),
        ("29/06/2024", "2024-06-29"),
        ("Jun 29, 2024", "2024-06-29"),
        ("29 June 2024", "2024-06-29"),
    ],
)
def test_normalize_valid_dates(raw_date, expected):
    assert DateNormalizer().normalize(raw_date) == expected


def test_normalize_datetime():
    assert DateNormalizer().normalize(datetime(2024, 6, 29, 13, 30)) == "2024-06-29"


@pytest.mark.parametrize(
    "raw_date",
    [
        None,
        "",
        "   ",
        "present",
        "current",
        "now",
        "not-a-date",
        "2024-99-99",
        "1800",
        "2200",
    ],
)
def test_invalid_dates_return_none(raw_date):
    assert DateNormalizer().normalize(raw_date) is None
