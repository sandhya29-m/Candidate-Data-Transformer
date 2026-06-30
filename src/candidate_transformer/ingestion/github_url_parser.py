"""GitHub profile URL parser backed by the GitHub REST API."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

from pydantic import ValidationError

from candidate_transformer.domain import CandidateRecord
from candidate_transformer.ingestion.base import CandidateParser
from candidate_transformer.ingestion.exceptions import ParserSchemaError, ParserValidationError
from candidate_transformer.services.github_service import GitHubAPIClient, GitHubAPIError
from candidate_transformer.utils import LinkClassifier

logger = logging.getLogger(__name__)


class GitHubProfileURLParser(CandidateParser):
    """Parse a GitHub profile URL into a ``CandidateRecord`` using the REST API."""

    def __init__(
        self,
        *,
        client: GitHubAPIClient | None = None,
        link_classifier: LinkClassifier | None = None,
        source_name: str = "github_api",
    ) -> None:
        """Initialize the parser.

        Args:
            client: Optional GitHub API client, useful for tests.
            source_name: Human-readable source name stored on the parsed record.
        """
        self._client = client or GitHubAPIClient()
        self._link_classifier = link_classifier or LinkClassifier()
        self._source_name = source_name

    def parse(self, source_path: str) -> list[CandidateRecord]:
        """Fetch and parse a public GitHub profile URL."""
        profile_url = str(source_path).strip()
        username = self.extract_username(profile_url)
        logger.info("Fetching GitHub profile", extra={"username": username})

        profile = self._client.fetch_profile(username)
        repositories = self._client.fetch_repositories(username)

        try:
            record = self._profile_to_record(profile, repositories=repositories, profile_url=profile_url)
        except (ValidationError, ValueError) as exc:
            logger.exception("GitHub API data could not produce a valid candidate", extra={"username": username})
            raise ParserValidationError("GitHub profile did not contain usable candidate data.") from exc

        logger.info(
            "Parsed GitHub profile URL",
            extra={"username": username, "repositories": len(repositories)},
        )
        return [record]

    def extract_username(self, profile_url: str) -> str:
        """Extract a GitHub username from a profile URL."""
        parsed_url = urlparse(profile_url.strip())
        if parsed_url.scheme not in {"http", "https"}:
            raise ParserSchemaError("GitHub profile URL must start with http:// or https://.")

        host = parsed_url.netloc.casefold()
        if host.startswith("www."):
            host = host[4:]
        if host != "github.com":
            raise ParserSchemaError("GitHub profile URL must use github.com.")

        path_parts = [part for part in parsed_url.path.split("/") if part]
        if not path_parts:
            raise ParserSchemaError("GitHub profile URL must include a username.")

        username = path_parts[0]
        if username.casefold() in {"orgs", "organizations", "settings", "marketplace", "features"}:
            raise ParserSchemaError("GitHub profile URL must point to a user profile.")
        return username

    def _profile_to_record(
        self,
        profile: dict[str, Any],
        *,
        repositories: list[dict[str, Any]],
        profile_url: str,
    ) -> CandidateRecord:
        """Convert GitHub API profile data into ``CandidateRecord``."""
        username = self._get_optional_text(profile, "login")
        github_url = self._get_optional_text(profile, "html_url") or profile_url
        bio = self._get_optional_text(profile, "bio")
        company = self._get_optional_text(profile, "company")
        location = self._get_optional_text(profile, "location")
        blog = self._get_optional_text(profile, "blog")
        email = self._get_optional_text(profile, "email")
        languages = self._extract_languages(repositories)

        links = [github_url]
        blog_link = self._link_classifier.classify(blog)
        if blog_link is not None:
            links.append(blog_link.url)

        if not any([username, github_url, bio, company, location, email, blog, repositories, languages]):
            raise ValueError("GitHub profile does not contain extractable candidate information")

        return CandidateRecord(
            source={
                "source_type": "github",
                "source_name": self._source_name,
                "source_record_id": username,
                "source_uri": profile_url,
            },
            external_id=username,
            full_name=self._get_optional_text(profile, "name"),
            emails=[email] if email is not None else [],
            location=location,
            links=links,
            headline=bio,
            skills=languages,
            experience=self._repository_entries(repositories),
            raw_values=self._raw_values(
                username=username,
                github_url=github_url,
                bio=bio,
                company=company,
                location=location,
                email=email,
                blog=blog,
                languages=languages,
                repositories=repositories,
                profile=profile,
            ),
            raw_payload={"profile": profile, "repositories": repositories},
        )

    def _extract_languages(self, repositories: list[dict[str, Any]]) -> list[str]:
        """Derive programming languages from repository metadata."""
        languages: list[str] = []
        seen: set[str] = set()
        for repository in repositories:
            language = repository.get("language")
            if language in (None, ""):
                continue
            language_text = str(language)
            key = language_text.casefold()
            if key not in seen:
                languages.append(language_text)
                seen.add(key)
        return languages

    def _repository_count(self, repositories: list[dict[str, Any]]) -> int:
        """Return public repository count from fetched repositories."""
        return len(repositories)

    def _repository_entries(self, repositories: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Return useful public repository data as raw entries."""
        entries: list[dict[str, Any]] = []
        for repository in repositories:
            entries.append(
                {
                    "name": repository.get("name"),
                    "full_name": repository.get("full_name"),
                    "html_url": repository.get("html_url"),
                    "description": repository.get("description"),
                    "language": repository.get("language"),
                    "stargazers_count": repository.get("stargazers_count"),
                    "forks_count": repository.get("forks_count"),
                    "updated_at": repository.get("updated_at"),
                }
            )
        return entries

    def _raw_values(
        self,
        *,
        username: str | None,
        github_url: str | None,
        bio: str | None,
        company: str | None,
        location: str | None,
        blog: str | None,
        email: str | None,
        languages: list[str],
        repositories: list[dict[str, Any]],
        profile: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Capture extracted GitHub values for provenance."""
        raw_values: list[dict[str, Any]] = []
        for field_name, source_key, value in (
            ("username", "login", username),
            ("github_url", "html_url", github_url),
            ("bio", "bio", bio),
            ("company", "company", company),
            ("location", "location", location),
            ("emails", "email", email),
            ("blog", "blog", blog),
            ("public_repos", "public_repos", profile.get("public_repos")),
            ("followers", "followers", profile.get("followers")),
            ("following", "following", profile.get("following")),
        ):
            if value not in (None, ""):
                raw_values.append({"field_name": field_name, "source_key": source_key, "value": value})
        if languages:
            raw_values.append({"field_name": "languages", "source_key": "repositories.language", "value": languages})
        raw_values.append({"field_name": "repositories", "source_key": "repositories", "value": repositories})
        return raw_values

    def _get_optional_text(self, payload: dict[str, Any], key: str) -> str | None:
        """Return an API field as text when present."""
        value = payload.get(key)
        if value in (None, ""):
            return None
        return str(value)
