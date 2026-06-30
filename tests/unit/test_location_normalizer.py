"""Unit tests for location normalization."""

from candidate_transformer.normalization import LocationNormalizer


def test_normalize_city_region_country():
    location = LocationNormalizer().normalize("San Francisco, CA, USA")

    assert location is not None
    assert location.city == "San Francisco"
    assert location.region == "CA"
    assert location.country == "United States"
    assert location.raw == "San Francisco, CA, USA"


def test_normalize_city_country():
    location = LocationNormalizer().normalize("London, UK")

    assert location is not None
    assert location.city == "London"
    assert location.region is None
    assert location.country == "United Kingdom"


def test_preserves_unknown_country_as_location_text():
    location = LocationNormalizer().normalize("Remote")

    assert location is not None
    assert location.city == "Remote"
    assert location.country is None


def test_custom_country_mapping():
    location = LocationNormalizer({"de": "Germany"}).normalize("Berlin, DE")

    assert location is not None
    assert location.city == "Berlin"
    assert location.country == "Germany"


def test_invalid_location_returns_none():
    normalizer = LocationNormalizer()

    assert normalizer.normalize(None) is None
    assert normalizer.normalize("") is None
    assert normalizer.normalize("   ") is None
