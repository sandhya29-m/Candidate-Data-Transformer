"""Location normalization utilities."""

from __future__ import annotations

import logging
from collections.abc import Mapping

from candidate_transformer.domain import Location

logger = logging.getLogger(__name__)


class LocationNormalizer:
    """Normalize location strings into structured location data.

    The normalizer standardizes country names using a configurable alias map.
    It does not geocode or infer missing countries; unknown location parts are
    preserved as city/region text instead of guessed.
    """

    DEFAULT_COUNTRY_MAPPINGS: dict[str, str] = {
        "usa": "United States",
        "us": "United States",
        "u.s.": "United States",
        "u.s.a.": "United States",
        "united states": "United States",
        "united states of america": "United States",
        "uk": "United Kingdom",
        "u.k.": "United Kingdom",
        "great britain": "United Kingdom",
        "britain": "United Kingdom",
        "england": "United Kingdom",
        "united kingdom": "United Kingdom",
        "india": "India",
        "in": "India",
        "canada": "Canada",
        "ca": "Canada",
    }

    def __init__(self, country_mappings: Mapping[str, str] | None = None) -> None:
        """Initialize the normalizer.

        Args:
            country_mappings: Optional country alias-to-canonical mapping.
                Custom mappings are merged with defaults and override defaults.
        """
        mappings = dict(self.DEFAULT_COUNTRY_MAPPINGS)
        if country_mappings is not None:
            mappings.update(country_mappings)

        self._country_mappings = {
            self._normalize_lookup_key(alias): canonical.strip()
            for alias, canonical in mappings.items()
            if alias.strip() and canonical.strip()
        }

    def normalize(self, location: str | None) -> Location | None:
        """Return a structured location or ``None`` for invalid input."""
        if location is None:
            logger.debug("Location is None")
            return None

        raw_location = location.strip()
        if not raw_location:
            logger.debug("Location is blank")
            return None

        parts = [part.strip() for part in raw_location.split(",") if part.strip()]
        if not parts:
            logger.debug("Location has no usable parts", extra={"location": location})
            return None

        country = self._canonical_country(parts[-1])
        city: str | None = None
        region: str | None = None

        if country is not None:
            location_parts = parts[:-1]
        else:
            location_parts = parts

        if len(location_parts) == 1:
            city = location_parts[0]
        elif len(location_parts) >= 2:
            city = location_parts[0]
            region = ", ".join(location_parts[1:])

        if country is None and len(parts) == 1:
            logger.info("Location country was not recognized", extra={"location": raw_location})

        try:
            return Location(city=city, region=region, country=country, raw=raw_location)
        except ValueError:
            logger.exception("Failed to build normalized location", extra={"location": raw_location})
            return None

    def _canonical_country(self, value: str) -> str | None:
        """Return the canonical country name for a country alias."""
        return self._country_mappings.get(self._normalize_lookup_key(value))

    def _normalize_lookup_key(self, value: str) -> str:
        """Create a case-insensitive country lookup key."""
        return " ".join(value.strip().casefold().split())
