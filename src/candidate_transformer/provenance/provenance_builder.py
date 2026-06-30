"""Build field-level provenance for candidate records.

Provenance explains where each field value came from, how it was merged, and
how much confidence the system has in that field. This module keeps provenance
construction separate from parsing, merging, and output formatting.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from candidate_transformer.domain import CandidateRecord
from candidate_transformer.scoring import ConfidenceCalculator

logger = logging.getLogger(__name__)


class FieldProvenance(BaseModel):
    """Provenance metadata for one candidate field observation."""

    model_config = ConfigDict(extra="forbid")

    source: str = Field(..., min_length=1, description="Source that supplied or contributed the field.")
    confidence: float = Field(..., ge=0, le=1, description="Confidence assigned to the field.")
    merge_method: str = Field(..., min_length=1, description="Method used to select or combine the field.")
    timestamp: datetime | None = Field(default=None, description="Optional source ingestion timestamp.")
    source_key: str | None = Field(default=None, description="Original source field key, column, or selector.")


class ProvenanceBuilder:
    """Build provenance information for every supported candidate field."""

    DEFAULT_MERGE_METHODS: dict[str, str] = {
        "external_id": "source_priority",
        "full_name": "source_priority",
        "emails": "union_deduplicate",
        "phones": "union_deduplicate",
        "location": "source_priority",
        "links": "union_deduplicate",
        "headline": "source_priority",
        "years_experience": "source_priority",
        "skills": "union_deduplicate",
        "experience": "union_deduplicate",
        "education": "union_deduplicate",
        "projects": "union_deduplicate",
        "certifications": "union_deduplicate",
        "resume_summary": "source_priority",
    }

    RAW_FIELD_ALIASES = ConfidenceCalculator.RAW_FIELD_ALIASES

    def __init__(
        self,
        *,
        confidence_calculator: ConfidenceCalculator | None = None,
        merge_methods: Mapping[str, str] | None = None,
        include_timestamps: bool = True,
    ) -> None:
        """Initialize the provenance builder.

        Args:
            confidence_calculator: Optional calculator used to score fields.
            merge_methods: Optional field-to-merge-method overrides.
            include_timestamps: Whether to include source ingestion timestamps.
        """
        self._confidence_calculator = confidence_calculator or ConfidenceCalculator()
        self._merge_methods = dict(self.DEFAULT_MERGE_METHODS)
        if merge_methods is not None:
            self._merge_methods.update(merge_methods)
        self._include_timestamps = include_timestamps

    def build(self, record: CandidateRecord) -> dict[str, list[FieldProvenance]]:
        """Return provenance entries for every supported candidate field."""
        logger.info(
            "Building candidate provenance",
            extra={"source_type": record.source.source_type, "source_name": record.source.source_name},
        )

        confidence_result = self._confidence_calculator.calculate(record)
        provenance: dict[str, list[FieldProvenance]] = {
            field_name: [] for field_name in self._merge_methods
        }

        raw_entries = self._entries_from_raw_values(record, confidence_result.field_confidence)
        for field_name, entries in raw_entries.items():
            provenance[field_name].extend(entries)

        for field_name in provenance:
            if provenance[field_name] or not self._field_has_value(record, field_name):
                continue
            provenance[field_name].append(
                self._build_entry(
                    source=self._source_label(record),
                    confidence=confidence_result.field_confidence.get(field_name, 0.0),
                    merge_method=self._merge_methods[field_name],
                    timestamp=record.source.ingested_at,
                    source_key=None,
                )
            )

        logger.info("Built candidate provenance", extra={"field_count": len(provenance)})
        return provenance

    def _entries_from_raw_values(
        self,
        record: CandidateRecord,
        field_confidence: dict[str, float],
    ) -> dict[str, list[FieldProvenance]]:
        """Build provenance entries from raw field values."""
        entries: dict[str, list[FieldProvenance]] = {field_name: [] for field_name in self._merge_methods}
        seen: set[tuple[str, str, str | None]] = set()

        for raw_value in record.raw_values:
            field_name = self.RAW_FIELD_ALIASES.get(raw_value.field_name, raw_value.field_name)
            if field_name not in entries:
                continue

            source, source_key = self._split_source_key(record, raw_value.source_key)
            key = (field_name, source, source_key)
            if key in seen:
                continue
            seen.add(key)

            entries[field_name].append(
                self._build_entry(
                    source=source,
                    confidence=field_confidence.get(field_name, 0.0),
                    merge_method=self._merge_methods[field_name],
                    timestamp=self._timestamp_for_source(record, source),
                    source_key=source_key,
                )
            )

        return entries

    def _build_entry(
        self,
        *,
        source: str,
        confidence: float,
        merge_method: str,
        timestamp: datetime | None,
        source_key: str | None,
    ) -> FieldProvenance:
        """Create one provenance entry."""
        return FieldProvenance(
            source=source,
            confidence=round(confidence, 4),
            merge_method=merge_method,
            timestamp=timestamp if self._include_timestamps else None,
            source_key=source_key,
        )

    def _split_source_key(self, record: CandidateRecord, source_key: str | None) -> tuple[str, str | None]:
        """Split source-qualified raw keys such as ``linkedin:headline``."""
        if source_key and ":" in source_key:
            source, key = source_key.split(":", 1)
            return source, key
        return self._source_label(record), source_key

    def _timestamp_for_source(self, record: CandidateRecord, source: str) -> datetime | None:
        """Find the timestamp for a source label, including merged records."""
        raw_payload = record.raw_payload or {}
        merged_from = raw_payload.get("merged_from", [])
        if isinstance(merged_from, list):
            for item in merged_from:
                if not isinstance(item, dict):
                    continue
                source_info = item.get("source", {})
                if not isinstance(source_info, dict):
                    continue
                labels = {str(source_info.get("source_type", "")), str(source_info.get("source_name", ""))}
                if source in labels:
                    timestamp = source_info.get("ingested_at")
                    if isinstance(timestamp, datetime):
                        return timestamp
                    if isinstance(timestamp, str):
                        try:
                            return datetime.fromisoformat(timestamp)
                        except ValueError:
                            return None
        return record.source.ingested_at

    def _field_has_value(self, record: CandidateRecord, field_name: str) -> bool:
        """Return whether a candidate field has a usable value."""
        value = getattr(record, field_name, None)
        if isinstance(value, list):
            return bool(value)
        return value not in (None, "")

    def _source_label(self, record: CandidateRecord) -> str:
        """Return the best source label for a record."""
        return record.source.source_name or record.source.source_type
