"""LinkedIn profile parser.

The parser converts LinkedIn profile JSON into the reusable ``CandidateRecord``
model. It extracts common LinkedIn fields without normalizing them, preserving
raw experience, education, skills, and the original profile payload for later
normalization and provenance tracking.
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


class LinkedInParser(CandidateParser):
    """Parse LinkedIn profile JSON into a ``CandidateRecord``."""

    def __init__(self, *, source_name: str = "linkedin_profile") -> None:
        """Initialize the parser.

        Args:
            source_name: Human-readable source name stored on the parsed record.
        """
        self._source_name = source_name

    def parse(self, source_path: str | Path) -> list[CandidateRecord]:
        """Read a LinkedIn profile JSON file and return one candidate record."""
        json_path = Path(source_path)
        logger.info("Parsing LinkedIn profile", extra={"source_path": str(json_path)})

        if not json_path.exists():
            logger.error("LinkedIn profile file not found", extra={"source_path": str(json_path)})
            raise ParserFileNotFoundError(f"LinkedIn profile file not found: {json_path}")

        payload = self._read_json(json_path)
        profile = self._extract_profile(payload)

        try:
            record = self._profile_to_record(profile, source_path=json_path, original_payload=payload)
        except (ValidationError, ValueError) as exc:
            logger.exception("LinkedIn profile could not produce a valid candidate", extra={"source_path": str(json_path)})
            raise ParserValidationError(f"LinkedIn profile contains no valid candidate record: {json_path}") from exc

        logger.info(
            "Parsed LinkedIn profile",
            extra={"source_path": str(json_path), "profile_url": record.links[0] if record.links else None},
        )
        return [record]

    def _read_json(self, json_path: Path) -> Any:
        """Read and decode LinkedIn profile JSON."""
        try:
            return json.loads(json_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            logger.exception("LinkedIn profile JSON is invalid", extra={"source_path": str(json_path)})
            raise ParserSchemaError(f"LinkedIn profile is not valid JSON: {json_path}") from exc
        except OSError as exc:
            logger.exception("Failed to read LinkedIn profile JSON", extra={"source_path": str(json_path)})
            raise ParserReadError(f"Could not read LinkedIn profile '{json_path}': {exc}") from exc

    def _extract_profile(self, payload: Any) -> dict[str, Any]:
        """Extract the LinkedIn profile object from common export shapes."""
        if not isinstance(payload, dict):
            raise ParserSchemaError("LinkedIn profile JSON root must be an object")

        profile = payload.get("linkedin_profile") or payload.get("profile") or payload
        if not isinstance(profile, dict):
            raise ParserSchemaError("LinkedIn profile JSON must contain a profile object")

        return profile

    def _profile_to_record(
        self,
        profile: dict[str, Any],
        *,
        source_path: Path,
        original_payload: dict[str, Any],
    ) -> CandidateRecord:
        """Map LinkedIn profile fields into ``CandidateRecord``."""
        name = self._first_text(profile, "name", "full_name", "fullName")
        headline = self._first_text(profile, "headline", "summary", "title")
        profile_url = self._first_text(profile, "profile_url", "url", "linkedin_url", "public_profile_url")
        experience = self._raw_list(profile, "experience", "positions", "work_experience")
        education = self._raw_list(profile, "education", "schools", "education_history")
        skills = self._string_list(profile, "skills", "skill_names")

        if not any([name, headline, profile_url, experience, education, skills]):
            raise ValueError("LinkedIn profile does not contain extractable candidate information")

        return CandidateRecord(
            source={
                "source_type": "linkedin",
                "source_name": self._source_name,
                "source_record_id": profile_url,
                "source_uri": str(source_path),
            },
            external_id=profile_url,
            full_name=name,
            links=[profile_url] if profile_url is not None else [],
            headline=headline,
            skills=skills,
            experience=experience,
            education=education,
            raw_values=self._get_raw_values(
                profile,
                name=name,
                headline=headline,
                profile_url=profile_url,
                experience=experience,
                education=education,
                skills=skills,
            ),
            raw_payload={"profile": profile, "payload": original_payload},
        )

    def _first_text(self, payload: dict[str, Any], *keys: str) -> str | None:
        """Return the first non-empty text value from a set of keys."""
        for key in keys:
            value = payload.get(key)
            if value not in (None, ""):
                return str(value)
        return None

    def _raw_list(self, payload: dict[str, Any], *keys: str) -> list[dict[str, Any]]:
        """Return raw list entries from the first present LinkedIn field."""
        value = self._first_present(payload, *keys)
        if value is None:
            return []

        values = value if isinstance(value, list) else [value]
        raw_entries: list[dict[str, Any]] = []
        for item in values:
            if isinstance(item, dict):
                raw_entries.append(item)
            elif item not in ("", None):
                raw_entries.append({"raw": item})

        return raw_entries

    def _string_list(self, payload: dict[str, Any], *keys: str) -> list[str]:
        """Return skill strings from scalar, list, or common LinkedIn value objects."""
        value = self._first_present(payload, *keys)
        if value is None:
            return []

        values = value if isinstance(value, list) else [value]
        skills: list[str] = []
        for item in values:
            text = self._extract_string_value(item)
            if text is not None:
                skills.append(text)

        return skills

    def _first_present(self, payload: dict[str, Any], *keys: str) -> Any:
        """Return the first present value from a set of keys."""
        for key in keys:
            value = payload.get(key)
            if value is not None:
                return value
        return None

    def _extract_string_value(self, value: Any) -> str | None:
        """Extract text from scalar values or common LinkedIn skill objects."""
        if value in (None, ""):
            return None

        if isinstance(value, dict):
            for key in ("name", "skill", "value", "label"):
                nested_value = value.get(key)
                if nested_value not in (None, ""):
                    return str(nested_value)
            return None

        return str(value)

    def _get_raw_values(
        self,
        profile: dict[str, Any],
        *,
        name: str | None,
        headline: str | None,
        profile_url: str | None,
        experience: list[dict[str, Any]],
        education: list[dict[str, Any]],
        skills: list[str],
    ) -> list[dict[str, Any]]:
        """Capture extracted LinkedIn values for provenance."""
        raw_values: list[dict[str, Any]] = []

        if name is not None:
            raw_values.append({"field_name": "name", "source_key": self._matched_key(profile, "name", "full_name", "fullName"), "value": name})
        if headline is not None:
            raw_values.append({"field_name": "headline", "source_key": self._matched_key(profile, "headline", "summary", "title"), "value": headline})
        if profile_url is not None:
            raw_values.append(
                {
                    "field_name": "profile_url",
                    "source_key": self._matched_key(profile, "profile_url", "url", "linkedin_url", "public_profile_url"),
                    "value": profile_url,
                }
            )
        if experience:
            raw_values.append({"field_name": "experience", "source_key": self._matched_key(profile, "experience", "positions", "work_experience"), "value": experience})
        if education:
            raw_values.append({"field_name": "education", "source_key": self._matched_key(profile, "education", "schools", "education_history"), "value": education})
        if skills:
            raw_values.append({"field_name": "skills", "source_key": self._matched_key(profile, "skills", "skill_names"), "value": skills})

        return raw_values

    def _matched_key(self, payload: dict[str, Any], *keys: str) -> str:
        """Return the first key present in the profile payload."""
        for key in keys:
            if key in payload:
                return key
        return keys[0]
