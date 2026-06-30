"""Phone number normalization utilities."""

from __future__ import annotations

import phonenumbers


class PhoneNormalizer:
    """Normalize valid phone numbers into E.164 format.

    The normalizer accepts international numbers such as ``+14155552671`` and
    local numbers that can be interpreted with a default country/region. Invalid
    or impossible numbers return ``None`` instead of raising parsing errors.
    """

    def __init__(self, default_region: str = "US") -> None:
        """Initialize the normalizer.

        Args:
            default_region: ISO 3166-1 alpha-2 region used for numbers without
                an explicit country code.
        """
        self._default_region = default_region.upper()

    def normalize(self, phone_number: str | None, *, region: str | None = None) -> str | None:
        """Return an E.164 phone number or ``None`` when invalid.

        Args:
            phone_number: Raw phone number text from a candidate source.
            region: Optional ISO 3166-1 alpha-2 region override for this value.

        Returns:
            A phone number formatted as E.164, or ``None`` if parsing or
            validation fails.
        """
        if phone_number is None:
            return None

        raw_number = phone_number.strip()
        if not raw_number:
            return None

        parse_region = (region or self._default_region).upper()

        try:
            parsed_number = phonenumbers.parse(raw_number, parse_region)
        except phonenumbers.NumberParseException:
            return None

        if not phonenumbers.is_possible_number(parsed_number):
            return None

        if not phonenumbers.is_valid_number(parsed_number):
            return None

        return phonenumbers.format_number(parsed_number, phonenumbers.PhoneNumberFormat.E164)
