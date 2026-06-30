"""Intermediate candidate record returned by source parsers.

``CandidateRecord`` is the reusable contract between ingestion parsers and the
normalization layer. It captures common candidate signals in a source-agnostic
shape while preserving enough source metadata and raw values for provenance,
debugging, and later confidence scoring.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


CandidateSourceType = Literal["csv", "json", "github", "linkedin", "resume", "manual", "other"]


class SourceInfo(BaseModel):
    """Metadata describing where a parser obtained a candidate record."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    source_type: CandidateSourceType = Field(..., description="Type of parser or external source.")
    source_name: str | None = Field(default=None, min_length=1, description="Human-readable source name.")
    source_record_id: str | None = Field(default=None, min_length=1, description="Source-system record identifier.")
    source_uri: str | None = Field(default=None, min_length=1, description="File path, URL, or API endpoint.")
    ingested_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Timestamp when the parser produced the record.",
    )

    @field_validator("source_uri")
    @classmethod
    def validate_source_uri(cls, value: str | None) -> str | None:
        """Reject blank source URIs while allowing filesystem paths and URLs."""
        if value is not None and not value.strip():
            raise ValueError("source_uri cannot be blank")
        return value


class RawFieldValue(BaseModel):
    """Raw source value captured before normalization."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    field_name: str = Field(..., min_length=1, description="Canonical or parser-local field name.")
    value: Any = Field(..., description="Raw value exactly as observed by the parser.")
    source_key: str | None = Field(default=None, min_length=1, description="Original source key, column, or selector.")


class CandidateRecord(BaseModel):
    """Reusable parser output model for candidate data before normalization."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    source: SourceInfo = Field(..., description="Source metadata for the parsed record.")
    external_id: str | None = Field(default=None, min_length=1, description="Candidate identifier from the source.")
    full_name: str | None = Field(default=None, min_length=1, description="Candidate name as parsed.")
    emails: list[str] = Field(default_factory=list, description="Email values discovered by the parser.")
    phones: list[str] = Field(default_factory=list, description="Phone values discovered by the parser.")
    location: str | None = Field(default=None, min_length=1, description="Raw or lightly parsed location text.")
    links: list[str] = Field(default_factory=list, description="Profile, resume, portfolio, or website links.")
    headline: str | None = Field(default=None, min_length=1, description="Raw headline or summary.")
    years_experience: float | None = Field(default=None, ge=0, description="Parsed years of experience if available.")
    skills: list[str] = Field(default_factory=list, description="Skill names or phrases from the source.")
    experience: list[dict[str, Any]] = Field(default_factory=list, description="Raw work history entries.")
    education: list[dict[str, Any]] = Field(default_factory=list, description="Raw education entries.")
    projects: list[dict[str, Any]] = Field(default_factory=list, description="Raw project entries.")
    certifications: list[str] = Field(default_factory=list, description="Certification names from the source.")
    resume_summary: str | None = Field(default=None, min_length=1, description="Short extracted resume summary.")
    resume_file: str | None = Field(default=None, min_length=1, description="Resume file path or filename.")
    raw_values: list[RawFieldValue] = Field(
        default_factory=list,
        description="Optional raw field values retained for provenance and auditability.",
    )
    raw_payload: dict[str, Any] | None = Field(
        default=None,
        description="Optional full parser payload when retaining raw source data is required.",
    )

    @field_validator("emails", "phones", "links", "skills", "certifications")
    @classmethod
    def normalize_string_lists(cls, value: list[str]) -> list[str]:
        """Trim, reject blank entries, and deduplicate parser string lists."""
        normalized_values: list[str] = []
        seen: set[str] = set()

        for item in value:
            normalized = item.strip()
            if not normalized:
                raise ValueError("string lists cannot contain blank values")

            key = normalized.casefold()
            if key not in seen:
                normalized_values.append(normalized)
                seen.add(key)

        return normalized_values

    @model_validator(mode="after")
    def require_candidate_signal(self) -> CandidateRecord:
        """Require at least one candidate-identifying signal besides source metadata."""
        has_signal = any(
            [
                self.external_id,
                self.full_name,
                self.emails,
                self.phones,
                self.links,
                self.raw_payload,
            ]
        )
        if not has_signal:
            raise ValueError("candidate record must contain at least one identifying signal")
        return self
