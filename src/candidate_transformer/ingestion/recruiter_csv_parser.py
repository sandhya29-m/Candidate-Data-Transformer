"""Recruiter CSV parser.

This parser reads recruiter-provided CSV files and converts each usable row
into a ``CandidateRecord``. It intentionally does not normalize candidate
values into canonical forms; normalization belongs to the downstream
normalization layer.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
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


@dataclass(frozen=True)
class RecruiterCSVColumnMapping:
    """Column names used to read candidate fields from a recruiter CSV."""

    external_id: str = "candidate_id"
    full_name: str = "full_name"
    name: str = "name"
    emails: str = "emails"
    email: str = "email"
    phones: str = "phones"
    phone: str = "phone"
    location: str = "location"
    links: str = "links"
    github_url: str = "github_url"
    headline: str = "headline"
    title: str = "title"
    years_experience: str = "years_experience"
    skills: str = "skills"
    experience: str = "experience"
    education: str = "education"
    current_company: str = "current_company"
    current_title: str = "current_title"
    total_experience: str = "total_experience"
    current_location: str = "current_location"
    recruiter_notes: str = "recruiter_notes"
    resume_file: str = "resume_file"


class RecruiterCSVParser(CandidateParser):
    """Parse recruiter CSV rows into reusable ``CandidateRecord`` instances."""

    def __init__(
        self,
        *,
        column_mapping: RecruiterCSVColumnMapping | None = None,
        list_delimiter: str = ",",
        source_name: str = "recruiter_csv",
    ) -> None:
        """Initialize the parser.

        Args:
            column_mapping: Optional CSV column mapping for recruiter-specific headers.
            list_delimiter: Delimiter used for list-like CSV cells.
            source_name: Human-readable source name stored on each record.
        """
        self._column_mapping = column_mapping or RecruiterCSVColumnMapping()
        self._list_delimiter = list_delimiter
        self._source_name = source_name

    def parse(self, source_path: str | Path) -> list[CandidateRecord]:
        """Read a recruiter CSV file and convert valid rows into records.

        Invalid rows are skipped and logged with row numbers. File-level issues,
        missing required structure, and fully invalid files raise parser-specific
        exceptions.
        """
        csv_path = Path(source_path)
        logger.info("Parsing recruiter CSV", extra={"source_path": str(csv_path)})

        if not csv_path.exists():
            logger.error("Recruiter CSV file not found", extra={"source_path": str(csv_path)})
            raise ParserFileNotFoundError(f"Recruiter CSV file not found: {csv_path}")

        try:
            dataframe = pd.read_csv(csv_path, dtype=str, keep_default_na=False)
        except pd.errors.EmptyDataError as exc:
            logger.exception("Recruiter CSV is empty", extra={"source_path": str(csv_path)})
            raise ParserSchemaError(f"Recruiter CSV is empty: {csv_path}") from exc
        except OSError as exc:
            logger.exception("Failed to read recruiter CSV", extra={"source_path": str(csv_path)})
            raise ParserReadError(f"Could not read recruiter CSV '{csv_path}': {exc}") from exc
        except Exception as exc:
            logger.exception("Failed to parse recruiter CSV", extra={"source_path": str(csv_path)})
            raise ParserReadError(f"Could not parse recruiter CSV '{csv_path}': {exc}") from exc

        self._validate_columns(dataframe)

        records: list[CandidateRecord] = []
        invalid_rows: list[int] = []

        for index, row in dataframe.iterrows():
            row_number = int(index) + 2
            row_data = row.to_dict()

            try:
                records.append(self._row_to_record(row_data, row_number=row_number, source_path=csv_path))
            except (ValidationError, ValueError) as exc:
                invalid_rows.append(row_number)
                logger.warning(
                    "Skipping invalid recruiter CSV row",
                    extra={"source_path": str(csv_path), "row_number": row_number, "error": str(exc)},
                )

        if not records:
            logger.error(
                "Recruiter CSV did not contain valid candidate records",
                extra={"source_path": str(csv_path), "invalid_rows": invalid_rows},
            )
            raise ParserValidationError(f"Recruiter CSV contains no valid candidate records: {csv_path}")

        logger.info(
            "Parsed recruiter CSV",
            extra={"source_path": str(csv_path), "records": len(records), "invalid_rows": len(invalid_rows)},
        )
        return records

    def _validate_columns(self, dataframe: pd.DataFrame) -> None:
        """Validate that the CSV contains enough columns to identify candidates."""
        available_columns = set(dataframe.columns)
        identifying_columns = {
            self._column_mapping.external_id,
            self._column_mapping.full_name,
            self._column_mapping.name,
            self._column_mapping.emails,
            self._column_mapping.email,
            self._column_mapping.phones,
            self._column_mapping.phone,
            self._column_mapping.links,
            self._column_mapping.github_url,
        }

        if available_columns.isdisjoint(identifying_columns):
            expected = ", ".join(sorted(identifying_columns))
            raise ParserSchemaError(
                "Recruiter CSV must include at least one identifying column: "
                f"{expected}"
            )

    def _row_to_record(self, row: dict[str, Any], *, row_number: int, source_path: Path) -> CandidateRecord:
        """Convert one CSV row into a ``CandidateRecord``."""
        mapping = self._column_mapping

        return CandidateRecord(
            source={
                "source_type": "csv",
                "source_name": self._source_name,
                "source_record_id": self._get_optional_text(row, mapping.external_id),
                "source_uri": str(source_path),
            },
            external_id=self._get_optional_text(row, mapping.external_id),
            full_name=self._first_optional_text(row, mapping.full_name, mapping.name),
            emails=self._merge_lists(row, mapping.emails, mapping.email),
            phones=self._merge_lists(row, mapping.phones, mapping.phone),
            location=self._first_optional_text(row, mapping.location, mapping.current_location),
            links=self._merge_lists(row, mapping.links, mapping.github_url),
            headline=self._first_optional_text(row, mapping.headline, mapping.title, mapping.current_title),
            years_experience=self._first_optional_float(row, mapping.years_experience, mapping.total_experience),
            skills=self._get_list(row, mapping.skills),
            experience=self._get_experience(row),
            education=self._get_raw_entry_list(row, mapping.education),
            resume_file=self._get_optional_text(row, mapping.resume_file),
            raw_values=self._get_raw_values(row),
            raw_payload={"row_number": row_number, "columns": row},
        )

    def _first_optional_text(self, row: dict[str, Any], *columns: str) -> str | None:
        """Return the first non-empty text value across candidate columns."""
        for column in columns:
            value = self._get_optional_text(row, column)
            if value is not None:
                return value
        return None

    def _merge_lists(self, row: dict[str, Any], *columns: str) -> list[str]:
        """Merge list-like values from multiple possible columns."""
        values: list[str] = []
        seen: set[str] = set()
        for column in columns:
            for value in self._get_list(row, column):
                key = value.strip().casefold()
                if key and key not in seen:
                    values.append(value)
                    seen.add(key)
        return values

    def _get_optional_text(self, row: dict[str, Any], column: str) -> str | None:
        """Return cell text when present, otherwise ``None``."""
        value = row.get(column)
        if value is None:
            return None

        text = str(value)
        if text == "":
            return None
        return text

    def _get_list(self, row: dict[str, Any], column: str) -> list[str]:
        """Return a delimiter-split list from a CSV cell without canonical normalization."""
        value = self._get_optional_text(row, column)
        if value is None:
            return []
        return [item for item in value.split(self._list_delimiter) if item != ""]

    def _get_optional_float(self, row: dict[str, Any], column: str) -> float | None:
        """Return a float from a numeric CSV cell when present."""
        value = self._get_optional_text(row, column)
        if value is None:
            return None

        try:
            return float(value)
        except ValueError as exc:
            raise ValueError(f"column '{column}' must be numeric") from exc

    def _first_optional_float(self, row: dict[str, Any], *columns: str) -> float | None:
        """Return first present numeric value across possible columns."""
        for column in columns:
            value = self._get_optional_float(row, column)
            if value is not None:
                return value
        return None

    def _get_raw_entry_list(self, row: dict[str, Any], column: str) -> list[dict[str, Any]]:
        """Keep complex row values as raw text entries for later normalization."""
        value = self._get_optional_text(row, column)
        if value is None:
            return []
        return [{"raw": value}]

    def _get_experience(self, row: dict[str, Any]) -> list[dict[str, Any]]:
        """Build raw experience from explicit experience or recruiter columns."""
        mapping = self._column_mapping
        explicit_experience = self._get_raw_entry_list(row, mapping.experience)
        if explicit_experience:
            return explicit_experience

        company = self._get_optional_text(row, mapping.current_company)
        title = self._first_optional_text(row, mapping.title, mapping.current_title)
        if company is None and title is None:
            return []

        entry: dict[str, Any] = {}
        if company is not None:
            entry["company"] = company
        if title is not None:
            entry["title"] = title
        return [entry]

    def _get_raw_values(self, row: dict[str, Any]) -> list[dict[str, Any]]:
        """Capture non-empty raw CSV cells for provenance and debugging."""
        raw_values: list[dict[str, Any]] = []

        for column, value in row.items():
            if value == "":
                continue
            raw_values.append({"field_name": column, "source_key": column, "value": value})

        return raw_values
