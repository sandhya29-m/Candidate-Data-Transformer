"""Unit tests for email normalization."""

import pytest

from candidate_transformer.normalization import EmailNormalizer


@pytest.mark.parametrize(
    ("raw_email", "expected"),
    [
        (" Ada@Example.COM ", "ada@example.com"),
        ("\tGrace.Hopper@NAVY.MIL\n", "grace.hopper@navy.mil"),
        ("dev+jobs@example.co.uk", "dev+jobs@example.co.uk"),
    ],
)
def test_normalize_valid_email(raw_email, expected):
    assert EmailNormalizer().normalize(raw_email) == expected


@pytest.mark.parametrize(
    "raw_email",
    [
        None,
        "",
        "   ",
        "not-an-email",
        "ada@",
        "@example.com",
        "ada@example",
        "ada @example.com",
        "ada@example .com",
        ".ada@example.com",
        "ada.@example.com",
        "ada..lovelace@example.com",
        "ada@-example.com",
        "ada@example-.com",
    ],
)
def test_normalize_invalid_email_returns_none(raw_email):
    assert EmailNormalizer().normalize(raw_email) is None
