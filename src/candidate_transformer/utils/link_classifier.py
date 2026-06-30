"""Classify candidate profile links without crawling external websites."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True)
class LinkClassification:
    """Classified candidate link."""

    category: str
    url: str


class LinkClassifier:
    """Classify known candidate link hosts into stable categories."""

    def classify(self, url: str | None) -> LinkClassification | None:
        """Classify a URL into a candidate link category.

        Args:
            url: Raw URL value.

        Returns:
            A link classification, or ``None`` when the value is empty or not a URL.
        """
        if url is None:
            return None

        normalized_url = url.strip()
        if not normalized_url:
            return None
        if any(character.isspace() for character in normalized_url):
            return None

        parsed_url = urlparse(normalized_url)
        if not parsed_url.scheme:
            normalized_url = f"https://{normalized_url}"
            parsed_url = urlparse(normalized_url)

        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            return None

        host = parsed_url.netloc.casefold()
        if host.startswith("www."):
            host = host[4:]

        if "linkedin.com" in host:
            category = "linkedin"
        elif "leetcode.com" in host:
            category = "leetcode"
        elif "hackerrank.com" in host:
            category = "hackerrank"
        elif "github.com" in host:
            category = "github"
        elif self._looks_like_personal_site(host):
            category = "portfolio"
        else:
            category = "other"

        return LinkClassification(category=category, url=normalized_url)

    def _looks_like_personal_site(self, host: str) -> bool:
        """Return whether an unknown host should be treated as a portfolio."""
        known_non_portfolio_hosts = {
            "facebook.com",
            "instagram.com",
            "x.com",
            "twitter.com",
            "youtube.com",
        }
        return host not in known_non_portfolio_hosts
