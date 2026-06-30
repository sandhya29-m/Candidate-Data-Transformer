"""Merge duplicate candidate records.

The merge engine combines multiple ``CandidateRecord`` instances into one
deterministic record. Scalar conflicts are resolved by configurable source
priority, list fields are deduplicated, and source provenance is preserved.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from candidate_transformer.domain import CandidateRecord

logger = logging.getLogger(__name__)


class MergeError(Exception):
    """Raised when candidate records cannot be merged."""


@dataclass(frozen=True)
class RankedRecord:
    """Candidate record with deterministic merge ranking metadata."""

    record: CandidateRecord
    index: int
    priority: int


class MergeEngine:
    """Merge multiple candidate records using deterministic conflict rules."""

    _SCALAR_FIELDS = ("external_id", "full_name", "location", "headline", "years_experience", "resume_summary", "resume_file")
    _STRING_LIST_FIELDS = ("emails", "phones", "links", "skills", "certifications")
    _DICT_LIST_FIELDS = ("experience", "education", "projects")

    def __init__(self, source_priorities: dict[str, int] | None = None) -> None:
        """Initialize the merge engine.

        Args:
            source_priorities: Mapping where higher values indicate more trusted
                sources. Keys may be source types, such as ``linkedin``, or
                source names, such as ``recruiter_csv``.
        """
        self._source_priorities = source_priorities or {}

    def merge(self, records: list[CandidateRecord]) -> CandidateRecord:
        """Merge candidate records into one deterministic ``CandidateRecord``.

        Raises:
            MergeError: If no records are provided.
        """
        if not records:
            raise MergeError("Cannot merge an empty candidate record list")

        logger.info("Merging candidate records", extra={"record_count": len(records)})

        ranked_records = self._rank_records(records)
        merged_values: dict[str, Any] = {
            "source": self._build_merged_source(ranked_records),
            "raw_values": self._merge_raw_values(ranked_records),
            "raw_payload": self._build_merged_payload(ranked_records),
        }

        for field_name in self._SCALAR_FIELDS:
            merged_values[field_name] = self._select_scalar(ranked_records, field_name)

        for field_name in self._STRING_LIST_FIELDS:
            merged_values[field_name] = self._merge_string_list(ranked_records, field_name)

        for field_name in self._DICT_LIST_FIELDS:
            merged_values[field_name] = self._merge_dict_list(ranked_records, field_name)

        merged_record = CandidateRecord(**merged_values)
        logger.info(
            "Merged candidate records",
            extra={"record_count": len(records), "merged_external_id": merged_record.external_id},
        )
        return merged_record

    def _rank_records(self, records: list[CandidateRecord]) -> list[RankedRecord]:
        """Rank records by priority and stable source metadata."""
        ranked_records = [
            RankedRecord(record=record, index=index, priority=self._source_priority(record))
            for index, record in enumerate(records)
        ]
        return sorted(
            ranked_records,
            key=lambda item: (
                -item.priority,
                item.record.source.source_type,
                item.record.source.source_name or "",
                item.record.source.source_record_id or "",
                item.index,
            ),
        )

    def _source_priority(self, record: CandidateRecord) -> int:
        """Return configured priority for a record source."""
        source_name = record.source.source_name or ""
        return max(
            self._source_priorities.get(record.source.source_type, 0),
            self._source_priorities.get(source_name, 0),
        )

    def _build_merged_source(self, ranked_records: list[RankedRecord]) -> dict[str, Any]:
        """Build source metadata for the merged record."""
        top_record = ranked_records[0].record
        return {
            "source_type": "other",
            "source_name": "merge_engine",
            "source_record_id": self._select_scalar(ranked_records, "external_id"),
            "source_uri": top_record.source.source_uri,
            "ingested_at": self._earliest_ingested_at(ranked_records),
        }

    def _earliest_ingested_at(self, ranked_records: list[RankedRecord]) -> datetime:
        """Return the earliest source ingestion timestamp for deterministic output."""
        timestamps = [item.record.source.ingested_at for item in ranked_records]
        return min(timestamps) if timestamps else datetime.now(timezone.utc)

    def _select_scalar(self, ranked_records: list[RankedRecord], field_name: str) -> Any:
        """Select the first non-empty scalar value from the highest-ranked source."""
        for ranked_record in ranked_records:
            value = getattr(ranked_record.record, field_name)
            if value not in (None, "", []):
                return value
        return None

    def _merge_string_list(self, ranked_records: list[RankedRecord], field_name: str) -> list[str]:
        """Merge string lists by source priority and remove duplicates."""
        merged_values: list[str] = []
        seen: set[str] = set()

        for ranked_record in ranked_records:
            for value in getattr(ranked_record.record, field_name):
                key = value.strip().casefold()
                if key and key not in seen:
                    merged_values.append(value.strip())
                    seen.add(key)

        return merged_values

    def _merge_dict_list(self, ranked_records: list[RankedRecord], field_name: str) -> list[dict[str, Any]]:
        """Merge dictionary lists by source priority and remove duplicate entries."""
        merged_values: list[dict[str, Any]] = []
        seen: set[str] = set()

        for ranked_record in ranked_records:
            for value in getattr(ranked_record.record, field_name):
                key = self._stable_json_key(value)
                if key not in seen:
                    merged_values.append(value)
                    seen.add(key)

        return merged_values

    def _merge_raw_values(self, ranked_records: list[RankedRecord]) -> list[dict[str, Any]]:
        """Aggregate raw field values from all source records with source context."""
        raw_values: list[dict[str, Any]] = []
        seen: set[str] = set()

        for ranked_record in ranked_records:
            source = ranked_record.record.source
            for raw_value in ranked_record.record.raw_values:
                value = raw_value.model_dump()
                merged_value = {
                    "field_name": value["field_name"],
                    "source_key": self._provenance_source_key(source, value.get("source_key")),
                    "value": value["value"],
                }
                key = self._stable_json_key(merged_value)
                if key not in seen:
                    raw_values.append(merged_value)
                    seen.add(key)

        return raw_values

    def _build_merged_payload(self, ranked_records: list[RankedRecord]) -> dict[str, Any]:
        """Build structured provenance for every merged source record."""
        return {
            "merged_from": [
                {
                    "source": ranked_record.record.source.model_dump(mode="json"),
                    "priority": ranked_record.priority,
                    "raw_payload": ranked_record.record.raw_payload,
                }
                for ranked_record in ranked_records
            ]
        }

    def _provenance_source_key(self, source: Any, source_key: str | None) -> str:
        """Create a source-qualified provenance key."""
        source_label = source.source_name or source.source_type
        if source_key is None:
            return source_label
        return f"{source_label}:{source_key}"

    def _stable_json_key(self, value: Any) -> str:
        """Return a deterministic JSON key for deduplication."""
        return json.dumps(value, sort_keys=True, default=str, separators=(",", ":")).casefold()
