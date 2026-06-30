"""Date normalization utilities."""

from __future__ import annotations

import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class DateNormalizer:
    """Normalize common candidate date strings into ISO-compatible strings.

    The normalizer preserves input precision. Year-only values return ``YYYY``,
    year-month values return ``YYYY-MM``, and full dates return ``YYYY-MM-DD``.
    Invalid or unsupported dates return ``None``.
    """

    _FULL_DATE_FORMATS = (
        "%Y-%m-%d",
        "%m/%d/%Y",
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%m-%d-%Y",
        "%b %d, %Y",
        "%B %d, %Y",
        "%d %b %Y",
        "%d %B %Y",
    )
    _YEAR_MONTH_FORMATS = (
        "%Y-%m",
        "%m/%Y",
        "%b %Y",
        "%B %Y",
    )

    def normalize(self, date_value: str | datetime | None) -> str | None:
        """Return an ISO date string or ``None`` for invalid input."""
        if date_value is None:
            logger.debug("Date is None")
            return None

        if isinstance(date_value, datetime):
            return date_value.date().isoformat()

        raw_date = date_value.strip()
        if not raw_date:
            logger.debug("Date is blank")
            return None

        if raw_date.casefold() in {"present", "current", "now"}:
            logger.info("Relative current date cannot be converted to a fixed ISO date", extra={"date": raw_date})
            return None

        year_only = self._normalize_year(raw_date)
        if year_only is not None:
            return year_only

        year_month = self._normalize_with_formats(raw_date, self._YEAR_MONTH_FORMATS, "%Y-%m")
        if year_month is not None:
            return year_month

        full_date = self._normalize_with_formats(raw_date, self._FULL_DATE_FORMATS, "%Y-%m-%d")
        if full_date is not None:
            return full_date

        logger.info("Date could not be normalized", extra={"date": raw_date})
        return None

    def _normalize_year(self, value: str) -> str | None:
        """Normalize a year-only value."""
        if not (len(value) == 4 and value.isdigit()):
            return None

        year = int(value)
        if year < 1900 or year > 2100:
            return None
        return value

    def _normalize_with_formats(self, value: str, formats: tuple[str, ...], output_format: str) -> str | None:
        """Try parsing a date with multiple formats."""
        for date_format in formats:
            try:
                return datetime.strptime(value, date_format).strftime(output_format)
            except ValueError:
                continue
        return None
