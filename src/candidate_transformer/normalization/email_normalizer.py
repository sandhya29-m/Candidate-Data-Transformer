"""Email normalization utilities."""

from __future__ import annotations

import re


class EmailNormalizer:
    """Normalize and validate email addresses.

    The normalizer performs conservative cleanup only: it trims surrounding
    whitespace, lowercases the address, rejects values containing internal
    whitespace, and validates the result with a pragmatic email pattern.
    """

    _EMAIL_PATTERN = re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+$")

    def normalize(self, email: str | None) -> str | None:
        """Return a normalized email address or ``None`` when invalid.

        Args:
            email: Raw email value from a candidate source.

        Returns:
            A lowercased, trimmed email address when valid; otherwise ``None``.
        """
        if email is None:
            return None

        normalized = email.strip().lower()
        if not normalized:
            return None

        if any(character.isspace() for character in normalized):
            return None

        if not self._EMAIL_PATTERN.fullmatch(normalized):
            return None

        local_part, domain = normalized.rsplit("@", 1)
        if local_part.startswith(".") or local_part.endswith(".") or ".." in local_part:
            return None
        if any(part.startswith("-") or part.endswith("-") for part in domain.split(".")):
            return None

        return normalized
