"""Confidence scoring for candidate records.

The calculator assigns confidence scores to candidate fields based on source
evidence. It supports configurable source weights and produces an overall score
as a deterministic weighted average of field-level scores.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, Field

from candidate_transformer.domain import CandidateRecord

logger = logging.getLogger(__name__)


class ConfidenceResult(BaseModel):
    """Confidence scores calculated for a candidate record."""

    model_config = ConfigDict(extra="forbid")

    field_confidence: dict[str, float] = Field(..., description="Confidence score for each candidate field.")
    overall_confidence: float = Field(..., ge=0, le=1, description="Weighted overall confidence score.")


class ConfidenceCalculator:
    """Calculate field and overall confidence for a ``CandidateRecord``."""

    DEFAULT_SOURCE_WEIGHTS: dict[str, float] = {
        "linkedin": 0.9,
        "linkedin_profile": 0.9,
        "github": 0.8,
        "github_profile": 0.8,
        "json": 0.7,
        "ats_json": 0.7,
        "resume": 0.7,
        "csv": 0.6,
        "recruiter_csv": 0.6,
        "manual": 0.5,
        "other": 0.4,
        "merge_engine": 0.4,
    }

    DEFAULT_FIELD_WEIGHTS: dict[str, float] = {
        "external_id": 0.8,
        "full_name": 1.0,
        "emails": 1.0,
        "phones": 0.9,
        "location": 0.5,
        "links": 0.8,
        "headline": 0.4,
        "years_experience": 0.5,
        "skills": 0.7,
        "experience": 0.8,
        "education": 0.6,
        "projects": 0.5,
        "certifications": 0.4,
        "resume_summary": 0.3,
    }

    RAW_FIELD_ALIASES: dict[str, str] = {
        "name": "full_name",
        "username": "external_id",
        "candidate_id": "external_id",
        "profile_url": "links",
        "github_url": "links",
        "linkedin_url": "links",
        "bio": "headline",
        "languages": "skills",
        "repositories": "experience",
        "companies": "experience",
        "job_titles": "experience",
        "duration": "experience",
        "degree": "education",
        "college": "education",
        "graduation_year": "education",
        "project_names": "projects",
    }

    def __init__(
        self,
        *,
        source_weights: Mapping[str, float] | None = None,
        field_weights: Mapping[str, float] | None = None,
        default_source_weight: float = 0.4,
    ) -> None:
        """Initialize the calculator.

        Args:
            source_weights: Optional source weight overrides. Keys may be source
                types such as ``linkedin`` or source names such as
                ``linkedin_profile``.
            field_weights: Optional field weights for the overall average.
            default_source_weight: Weight used when a source has no configured
                entry.
        """
        self._source_weights = dict(self.DEFAULT_SOURCE_WEIGHTS)
        if source_weights is not None:
            self._source_weights.update(source_weights)

        self._field_weights = dict(self.DEFAULT_FIELD_WEIGHTS)
        if field_weights is not None:
            self._field_weights.update(field_weights)

        self._default_source_weight = self._clamp(default_source_weight)

    def calculate(self, record: CandidateRecord) -> ConfidenceResult:
        """Calculate confidence scores for a candidate record."""
        logger.info(
            "Calculating candidate confidence",
            extra={"source_type": record.source.source_type, "source_name": record.source.source_name},
        )

        field_confidence = {
            field_name: self._field_confidence(record, field_name)
            for field_name in self._field_weights
        }
        overall_confidence = self._overall_confidence(field_confidence)

        logger.info("Calculated candidate confidence", extra={"overall_confidence": overall_confidence})
        return ConfidenceResult(field_confidence=field_confidence, overall_confidence=overall_confidence)

    def _field_confidence(self, record: CandidateRecord, field_name: str) -> float:
        """Calculate confidence for one candidate field."""
        if not self._field_has_value(record, field_name):
            return 0.0

        source_labels = self._source_labels_for_field(record, field_name)
        if not source_labels:
            source_labels = self._record_source_labels(record)

        confidence = 1.0
        for source_label in sorted(source_labels):
            confidence *= 1 - self._source_weight(source_label)

        return round(1 - confidence, 4)

    def _overall_confidence(self, field_confidence: dict[str, float]) -> float:
        """Calculate weighted average confidence across fields."""
        weighted_total = 0.0
        total_weight = 0.0

        for field_name, confidence in field_confidence.items():
            if confidence == 0:
                continue
            weight = self._field_weights[field_name]
            weighted_total += confidence * weight
            total_weight += weight

        if total_weight == 0:
            return 0.0
        return round(weighted_total / total_weight, 4)

    def _field_has_value(self, record: CandidateRecord, field_name: str) -> bool:
        """Return whether a candidate field has a usable value."""
        value = getattr(record, field_name, None)
        if isinstance(value, list):
            return bool(value)
        return value not in (None, "")

    def _source_labels_for_field(self, record: CandidateRecord, field_name: str) -> set[str]:
        """Extract source labels that provided a field from raw provenance."""
        source_labels: set[str] = set()

        for raw_value in record.raw_values:
            raw_field = self.RAW_FIELD_ALIASES.get(raw_value.field_name, raw_value.field_name)
            if raw_field != field_name:
                continue

            source_key = raw_value.source_key or ""
            source_label = source_key.split(":", 1)[0] if ":" in source_key else None
            if source_label:
                source_labels.add(source_label)

        if source_labels:
            return source_labels

        return self._source_labels_from_merged_payload(record, field_name)

    def _source_labels_from_merged_payload(self, record: CandidateRecord, field_name: str) -> set[str]:
        """Fallback source extraction for merged records without field-specific raw values."""
        raw_payload = record.raw_payload or {}
        merged_from = raw_payload.get("merged_from", [])
        if not isinstance(merged_from, list):
            return set()

        labels: set[str] = set()
        for item in merged_from:
            if not isinstance(item, dict):
                continue
            source = item.get("source", {})
            if not isinstance(source, dict):
                continue
            source_type = source.get("source_type")
            source_name = source.get("source_name")
            if source_name:
                labels.add(str(source_name))
            elif source_type:
                labels.add(str(source_type))

        return labels if self._field_has_value(record, field_name) else set()

    def _record_source_labels(self, record: CandidateRecord) -> set[str]:
        """Return source labels for the record itself."""
        if record.source.source_name:
            return {record.source.source_name}
        return {record.source.source_type}

    def _source_weight(self, source_label: str) -> float:
        """Return a configured source weight clamped to 0..1."""
        return self._clamp(self._source_weights.get(source_label, self._default_source_weight))

    def _clamp(self, value: float) -> float:
        """Clamp numeric scores to the valid confidence range."""
        return max(0.0, min(1.0, float(value)))
