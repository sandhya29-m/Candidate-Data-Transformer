"""GitHub profile parser.

The parser converts GitHub profile JSON into the reusable ``CandidateRecord``
model. It extracts GitHub-specific signals without normalizing them, preserving
the original payload for downstream provenance, scoring, and normalization.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from candidate_transformer.domain import CandidateRecord
from candidate_transformer.ingestion.base import CandidateParser
from candidate_transformer.ingestion.exceptions import (
    ParserFileNotFoundError,
    ParserReadError,
    ParserSchemaError,
    ParserValidationError,
)

logger = logging.getLogger(__name__)


class GitHubProfileParser(CandidateParser):
    """Parse GitHub profile JSON into a ``CandidateRecord``."""

    def __init__(self, *, source_name: str = "github_profile") -> None:
        """Initialize the parser.

        Args:
            source_name: Human-readable source name stored on the parsed record.
        """
        self._source_name = source_name

    def parse(self, source_path: str | Path) -> list[CandidateRecord]:
        """Read a GitHub profile JSON file and return one candidate record."""
        json_path = Path(source_path)
        logger.info("Parsing GitHub profile", extra={"source_path": str(json_path)})

        if not json_path.exists():
            logger.error("GitHub profile file not found", extra={"source_path": str(json_path)})
            raise ParserFileNotFoundError(f"GitHub profile file not found: {json_path}")

        payload = self._read_json(json_path)
        profile = self._extract_profile(payload)
        repositories = self._extract_repositories(payload)

        try:
            record = self._profile_to_record(
                profile,
                repositories=repositories,
                source_path=json_path,
                original_payload=payload,
            )
        except (ValidationError, ValueError) as exc:
            logger.exception("GitHub profile could not produce a valid candidate", extra={"source_path": str(json_path)})
            raise ParserValidationError(f"GitHub profile contains no valid candidate record: {json_path}") from exc

        logger.info(
            "Parsed GitHub profile",
            extra={"source_path": str(json_path), "username": record.external_id, "repositories": len(repositories)},
        )
        return [record]

    def _read_json(self, json_path: Path) -> Any:
        """Read and decode GitHub profile JSON."""
        try:
            return json.loads(json_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            logger.exception("GitHub profile JSON is invalid", extra={"source_path": str(json_path)})
            raise ParserSchemaError(f"GitHub profile is not valid JSON: {json_path}") from exc
        except OSError as exc:
            logger.exception("Failed to read GitHub profile JSON", extra={"source_path": str(json_path)})
            raise ParserReadError(f"Could not read GitHub profile '{json_path}': {exc}") from exc

    def _extract_profile(self, payload: Any) -> dict[str, Any]:
        """Extract the GitHub user profile object from common export shapes."""
        if not isinstance(payload, dict):
            raise ParserSchemaError("GitHub profile JSON root must be an object")

        profile = payload.get("profile") or payload.get("user") or payload
        if not isinstance(profile, dict):
            raise ParserSchemaError("GitHub profile JSON must contain a profile object")

        return profile

    def _extract_repositories(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        """Extract repository objects from common GitHub export keys."""
        repositories = payload.get("repositories", payload.get("repos", []))
        if repositories is None:
            return []
        if not isinstance(repositories, list):
            raise ParserSchemaError("GitHub repositories must be a list")

        return [repository for repository in repositories if isinstance(repository, dict)]

    def _profile_to_record(
        self,
        profile: dict[str, Any],
        *,
        repositories: list[dict[str, Any]],
        source_path: Path,
        original_payload: dict[str, Any],
    ) -> CandidateRecord:
        """Map GitHub profile fields into ``CandidateRecord``."""
        username = self._get_optional_text(profile, "login") or self._get_optional_text(profile, "username")
        github_url = self._get_optional_text(profile, "html_url") or self._build_github_url(username)
        bio = self._get_optional_text(profile, "bio")
        languages = self._extract_languages(profile, repositories)

        if not any([username, github_url, bio, languages, repositories]):
            raise ValueError("GitHub profile does not contain extractable candidate information")

        return CandidateRecord(
            source={
                "source_type": "github",
                "source_name": self._source_name,
                "source_record_id": username,
                "source_uri": str(source_path),
            },
            external_id=username,
            full_name=self._get_optional_text(profile, "name"),
            location=self._get_optional_text(profile, "location"),
            links=[github_url] if github_url is not None else [],
            headline=bio,
            skills=languages,
            experience=self._repositories_to_raw_entries(repositories),
            raw_values=self._get_raw_values(profile, repositories, username=username, github_url=github_url, bio=bio),
            raw_payload={"profile": profile, "repositories": repositories, "payload": original_payload},
        )

    def _extract_languages(self, profile: dict[str, Any], repositories: list[dict[str, Any]]) -> list[str]:
        """Extract language strings from profile fields and repository metadata."""
        languages: list[str] = []
        explicit_languages = profile.get("languages", [])

        if isinstance(explicit_languages, list):
            languages.extend(str(language) for language in explicit_languages if language not in (None, ""))
        elif explicit_languages not in (None, ""):
            languages.append(str(explicit_languages))

        for repository in repositories:
            language = repository.get("language")
            if language not in (None, ""):
                languages.append(str(language))

        return languages

    def _repositories_to_raw_entries(self, repositories: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Return repositories as raw entries for later normalization."""
        return repositories

    def _get_raw_values(
        self,
        profile: dict[str, Any],
        repositories: list[dict[str, Any]],
        *,
        username: str | None,
        github_url: str | None,
        bio: str | None,
    ) -> list[dict[str, Any]]:
        """Capture extracted raw values for provenance."""
        raw_values: list[dict[str, Any]] = []

        if username is not None:
            raw_values.append({"field_name": "username", "source_key": "login", "value": username})
        if github_url is not None:
            raw_values.append({"field_name": "github_url", "source_key": "html_url", "value": github_url})
        if bio is not None:
            raw_values.append({"field_name": "bio", "source_key": "bio", "value": bio})

        raw_values.append({"field_name": "repositories", "source_key": "repositories", "value": repositories})

        languages = self._extract_languages(profile, repositories)
        if languages:
            raw_values.append({"field_name": "languages", "source_key": "languages/repositories.language", "value": languages})

        return raw_values

    def _get_optional_text(self, payload: dict[str, Any], key: str) -> str | None:
        """Return a profile field as text when present."""
        value = payload.get(key)
        if value in (None, ""):
            return None
        return str(value)

    def _build_github_url(self, username: str | None) -> str | None:
        """Build a GitHub profile URL from a username when no URL is provided."""
        if username is None:
            return None
        return f"https://github.com/{username}"
