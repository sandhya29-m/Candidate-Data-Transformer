"""Unit tests for phone number normalization."""

import pytest

from candidate_transformer.normalization import PhoneNormalizer


@pytest.mark.parametrize(
    ("raw_phone", "expected"),
    [
        ("+1 415 555 2671", "+14155552671"),
        ("(415) 555-2671", "+14155552671"),
        ("\t+44 20 7946 0958\n", "+442079460958"),
        ("+91 98765 43210", "+919876543210"),
    ],
)
def test_normalize_valid_phone_numbers(raw_phone, expected):
    assert PhoneNormalizer(default_region="US").normalize(raw_phone) == expected


def test_normalize_local_number_with_region_override():
    assert PhoneNormalizer(default_region="US").normalize("020 7946 0958", region="GB") == "+442079460958"


def test_normalize_local_number_with_default_region():
    assert PhoneNormalizer(default_region="GB").normalize("020 7946 0958") == "+442079460958"


@pytest.mark.parametrize(
    "raw_phone",
    [
        None,
        "",
        "   ",
        "not-a-phone",
        "123",
        "+1 000 000 0000",
        "+999 123456",
    ],
)
def test_normalize_invalid_phone_numbers_return_none(raw_phone):
    assert PhoneNormalizer().normalize(raw_phone) is None
