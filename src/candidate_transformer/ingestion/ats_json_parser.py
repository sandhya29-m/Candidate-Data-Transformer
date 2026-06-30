"""ATS JSON parser.

This parser reads Applicant Tracking System JSON exports and maps nested
vendor-specific fields into the reusable ``CandidateRecord`` model. It keeps
the mapping logic inside the ingestion layer and preserves raw mapped values
plus the original record payload for downstream provenance and diagnostics.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
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

FieldPaths = tuple[str, ...]


@dataclass(frozen=True)
class ATSJSONFieldMapping:
    """Nested JSON paths used to map ATS fields into ``CandidateRecord``."""

    records_path: str | None = "candidates"
    external_id: FieldPaths = ("candidate_id", "id", "candidate.id")
    full_name: FieldPaths = ("candidateName", "full_name", "name", "profile.full_name", "profile.name")
    emails: FieldPaths = ("mail", "email", "emails", "contact.emails", "profile.emails")
    phones: FieldPaths = ("phoneNumber", "phone", "phones", "contact.phones", "profile.phones")
    location: FieldPaths = ("current_location", "location", "profile.location", "address.formatted")
    links: FieldPaths = ("links", "profile.links", "social.links")
    headline: FieldPaths = ("headline", "current_title", "summary", "profile.headline")
    years_experience: FieldPaths = ("years_experience", "experience_years", "profile.years_experience")
    skills: FieldPaths = ("skills", "profile.skills")
    experience: FieldPaths = ("experience", "work_experience", "employment_history")
    education: FieldPaths = ("education", "education_history")


class ATSJSONParser(CandidateParser):
    """Parse ATS JSON exports into intermediate ``CandidateRecord`` instances."""

    def __init__(
        self,
        *,
        field_mapping: ATSJSONFieldMapping | None = None,
        source_name: str = "ats_json",
    ) -> None:
        """Initialize the parser.

        Args:
            field_mapping: Optional nested-path mapping for a specific ATS vendor.
            source_name: Human-readable source name stored on each record.
        """
        self._field_mapping = field_mapping or ATSJSONFieldMapping()
        self._source_name = source_name

    def parse(self, source_path: str | Path) -> list[CandidateRecord]:
        """Read ATS JSON and convert valid candidate payloads into records."""
        json_path = Path(source_path)
        logger.info("Parsing ATS JSON", extra={"source_path": str(json_path)})

        if not json_path.exists():
            logger.error("ATS JSON file not found", extra={"source_path": str(json_path)})
            raise ParserFileNotFoundError(f"ATS JSON file not found: {json_path}")

        payload = self._read_json(json_path)
        candidate_payloads = self._extract_candidate_payloads(payload)

        records: list[CandidateRecord] = []
        invalid_indexes: list[int] = []

        for index, candidate_payload in enumerate(candidate_payloads, start=1):
            try:
                records.append(self._payload_to_record(candidate_payload, record_index=index, source_path=json_path))
            except (ValidationError, ValueError) as exc:
                invalid_indexes.append(index)
                logger.warning(
                    "Skipping invalid ATS JSON candidate",
                    extra={"source_path": str(json_path), "record_index": index, "error": str(exc)},
                )

        if not records:
            logger.error(
                "ATS JSON did not contain valid candidate records",
                extra={"source_path": str(json_path), "invalid_records": invalid_indexes},
            )
            raise ParserValidationError(f"ATS JSON contains no valid candidate records: {json_path}")

        logger.info(
            "Parsed ATS JSON",
            extra={"source_path": str(json_path), "records": len(records), "invalid_records": len(invalid_indexes)},
        )
        return records

    def _read_json(self, json_path: Path) -> Any:
        """Read and decode a JSON file."""
        try:
            return json.loads(json_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            logger.exception("ATS JSON is invalid", extra={"source_path": str(json_path)})
            raise ParserSchemaError(f"ATS JSON is not valid JSON: {json_path}") from exc
        except OSError as exc:
            logger.exception("Failed to read ATS JSON", extra={"source_path": str(json_path)})
            raise ParserReadError(f"Could not read ATS JSON '{json_path}': {exc}") from exc

    def _extract_candidate_payloads(self, payload: Any) -> list[dict[str, Any]]:
        """Extract candidate objects from a single object, list, or nested collection."""
        if isinstance(payload, list):
            records = payload
        elif isinstance(payload, dict):
            records = self._extract_records_from_dict(payload)
        else:
            raise ParserSchemaError("ATS JSON root must be an object or a list")

        candidate_payloads = [record for record in records if isinstance(record, dict)]
        if not candidate_payloads:
            raise ParserSchemaError("ATS JSON does not contain candidate objects")

        return candidate_payloads

    def _extract_records_from_dict(self, payload: dict[str, Any]) -> list[Any]:
        """Extract record list from the configured records path or use the root object."""
        records_path = self._field_mapping.records_path
        if records_path is None:
            return [payload]

        nested_records = self._get_path(payload, records_path)
        if isinstance(nested_records, list):
            return nested_records
        if isinstance(nested_records, dict):
            return [nested_records]

        logger.info(
            "Configured ATS record path was not found; treating root object as one candidate",
            extra={"records_path": records_path},
        )
        return [payload]

    def _payload_to_record(
        self,
        payload: dict[str, Any],
        *,
        record_index: int,
        source_path: Path,
    ) -> CandidateRecord:
        """Map one ATS candidate payload into a ``CandidateRecord``."""
        mapping = self._field_mapping
        external_id = self._get_optional_text_from_paths(payload, mapping.external_id)

        return CandidateRecord(
            source={
                "source_type": "json",
                "source_name": self._source_name,
                "source_record_id": external_id,
                "source_uri": str(source_path),
            },
            external_id=external_id,
            full_name=self._get_optional_text_from_paths(payload, mapping.full_name),
            emails=self._get_string_list_from_paths(payload, mapping.emails),
            phones=self._get_string_list_from_paths(payload, mapping.phones),
            location=self._get_optional_text_from_paths(payload, mapping.location),
            links=self._get_string_list_from_paths(payload, mapping.links),
            headline=self._get_optional_text_from_paths(payload, mapping.headline),
            years_experience=self._get_optional_float_from_paths(payload, mapping.years_experience),
            skills=self._get_string_list_from_paths(payload, mapping.skills),
            experience=self._get_dict_list_from_paths(payload, mapping.experience),
            education=self._get_dict_list_from_paths(payload, mapping.education),
            raw_values=self._get_raw_values(payload),
            raw_payload={"record_index": record_index, "payload": payload},
        )

    def _get_optional_text_from_paths(self, payload: dict[str, Any], paths: FieldPaths) -> str | None:
        """Return the first present scalar value for a set of nested paths."""
        value = self._get_first_present_value(payload, paths)
        if value is None:
            return None

        if isinstance(value, dict):
            value = value.get("value") or value.get("name") or value.get("label")
        elif isinstance(value, list):
            value = next((item for item in value if item not in (None, "")), None)

        if value is None:
            return None

        text = str(value)
        if text == "":
            return None
        return text

    def _get_string_list_from_paths(self, payload: dict[str, Any], paths: FieldPaths) -> list[str]:
        """Return strings from the first present list-like ATS field."""
        value = self._get_first_present_value(payload, paths)
        if value is None:
            return []

        values = value if isinstance(value, list) else [value]
        extracted: list[str] = []
        for item in values:
            text = self._extract_string_value(item)
            if text is not None:
                extracted.append(text)

        return extracted

    def _get_optional_float_from_paths(self, payload: dict[str, Any], paths: FieldPaths) -> float | None:
        """Return a float from the first present numeric ATS field."""
        value = self._get_first_present_value(payload, paths)
        if value is None or value == "":
            return None

        try:
            return float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("years_experience must be numeric") from exc

    def _get_dict_list_from_paths(self, payload: dict[str, Any], paths: FieldPaths) -> list[dict[str, Any]]:
        """Return raw nested entries as dictionaries for downstream normalization."""
        value = self._get_first_present_value(payload, paths)
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

    def _get_raw_values(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        """Capture mapped raw values for provenance without flattening the full payload."""
        mapping = self._field_mapping
        field_paths: dict[str, FieldPaths] = {
            "external_id": mapping.external_id,
            "full_name": mapping.full_name,
            "emails": mapping.emails,
            "phones": mapping.phones,
            "location": mapping.location,
            "links": mapping.links,
            "headline": mapping.headline,
            "years_experience": mapping.years_experience,
            "skills": mapping.skills,
            "experience": mapping.experience,
            "education": mapping.education,
        }

        raw_values: list[dict[str, Any]] = []
        for field_name, paths in field_paths.items():
            matched_path, value = self._get_first_present_path_and_value(payload, paths)
            if matched_path is None or value in (None, ""):
                continue
            raw_values.append({"field_name": field_name, "source_key": matched_path, "value": value})

        return raw_values

    def _get_first_present_value(self, payload: dict[str, Any], paths: FieldPaths) -> Any:
        """Return the first value found for a set of nested paths."""
        _, value = self._get_first_present_path_and_value(payload, paths)
        return value

    def _get_first_present_path_and_value(self, payload: dict[str, Any], paths: FieldPaths) -> tuple[str | None, Any]:
        """Return the first matched path and value from an ordered path list."""
        for path in paths:
            value = self._get_path(payload, path)
            if value is not None:
                return path, value
        return None, None

    def _get_path(self, payload: Any, path: str) -> Any:
        """Resolve a dot-separated path against nested dicts and lists."""
        current = payload
        for segment in path.split("."):
            if isinstance(current, dict):
                current = current.get(segment)
            elif isinstance(current, list):
                current = self._extract_from_list(current, segment)
            else:
                return None

            if current is None:
                return None

        return current

    def _extract_from_list(self, values: list[Any], segment: str) -> Any:
        """Extract a path segment from every dictionary in a list."""
        if segment.isdigit():
            index = int(segment)
            return values[index] if 0 <= index < len(values) else None

        extracted = [item.get(segment) for item in values if isinstance(item, dict) and item.get(segment) is not None]
        if not extracted:
            return None
        return extracted

    def _extract_string_value(self, value: Any) -> str | None:
        """Extract a string from scalar or common ATS value objects."""
        if value is None or value == "":
            return None

        if isinstance(value, dict):
            for key in ("value", "email", "phone", "url", "name", "label"):
                nested_value = value.get(key)
                if nested_value not in (None, ""):
                    return str(nested_value)
            return None

        return str(value)
