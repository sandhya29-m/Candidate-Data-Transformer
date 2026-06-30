"""GitHub REST API service for public candidate profile data."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)


class GitHubAPIError(Exception):
    """Raised when GitHub API data cannot be fetched safely."""


@dataclass
class GitHubAPIClient:
    """Small GitHub REST API client for public profile and repository data."""

    timeout_seconds: int = 10

    def fetch_profile(self, username: str) -> dict[str, Any]:
        """Fetch a public GitHub user profile."""
        payload = self._get_json(f"https://api.github.com/users/{username}")
        if not isinstance(payload, dict):
            raise GitHubAPIError("GitHub profile response was not an object.")
        return payload

    def fetch_repositories(self, username: str) -> list[dict[str, Any]]:
        """Fetch public repositories for a GitHub user."""
        payload = self._get_json(f"https://api.github.com/users/{username}/repos?per_page=100&sort=updated")
        if not isinstance(payload, list):
            raise GitHubAPIError("GitHub repositories response was not a list.")
        return [item for item in payload if isinstance(item, dict)]

    def _get_json(self, url: str) -> Any:
        """Fetch JSON from GitHub and return the decoded payload."""
        request = Request(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "candidate-transformer",
            },
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            message = self._friendly_http_error(exc)
            logger.warning("GitHub API HTTP error", extra={"url": url, "status": exc.code, "error_message": message})
            raise GitHubAPIError(message) from exc
        except URLError as exc:
            logger.warning("GitHub API network error", extra={"url": url, "reason": str(exc.reason)})
            raise GitHubAPIError("Could not reach GitHub. Check your network connection and try again.") from exc
        except TimeoutError as exc:
            logger.warning("GitHub API timed out", extra={"url": url})
            raise GitHubAPIError("Could not reach GitHub. Check your network connection and try again.") from exc
        except json.JSONDecodeError as exc:
            logger.warning("GitHub API returned invalid JSON", extra={"url": url})
            raise GitHubAPIError("GitHub returned an invalid response. Please try again later.") from exc

    def _friendly_http_error(self, exc: HTTPError) -> str:
        """Return a user-friendly message for common GitHub HTTP failures."""
        if exc.code == 403:
            return "GitHub API rate limit reached or access was denied. Please wait and try again."
        if exc.code == 404:
            return "GitHub profile was not found. Check the profile URL and try again."
        return f"GitHub API request failed with status {exc.code}. Please try again later."
