"""Canonical candidate schema.

The models in this module define the normalized candidate representation used
after ingestion and normalization. Source-specific readers should translate
their raw payloads into this schema before matching, merging, scoring, or
writing output.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
DATE_PART_PATTERN = re.compile(r"^\d{4}(-\d{2})?$")
PHONE_PATTERN = re.compile(r"^\+?[0-9][0-9\s().-]{6,}$")


class Location(BaseModel):
    """Normalized candidate location."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    city: str | None = Field(default=None, min_length=1, description="Candidate city.")
    region: str | None = Field(default=None, min_length=1, description="State, province, or region.")
    country: str | None = Field(default=None, min_length=1, description="Candidate country.")
    raw: str | None = Field(default=None, min_length=1, description="Original unparsed location text.")

    @model_validator(mode="after")
    def require_at_least_one_location_value(self) -> Location:
        """Require location objects to contain at least one usable value."""
        if not any([self.city, self.region, self.country, self.raw]):
            raise ValueError("location must contain at least one value")
        return self


class CandidateLink(BaseModel):
    """External profile or contact link for a candidate."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    type: Literal["github", "linkedin", "leetcode", "hackerrank", "portfolio", "website", "resume", "other"] = Field(
        ...,
        description="Kind of candidate link.",
    )
    url: str = Field(..., min_length=1, description="Absolute URL for the candidate link.")

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        """Ensure candidate links are HTTP or HTTPS URLs."""
        if not value.startswith(("https://", "http://")):
            raise ValueError("link url must start with http:// or https://")
        return value


class Skill(BaseModel):
    """Normalized candidate skill."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(..., min_length=1, description="Canonical skill name.")
    category: str | None = Field(default=None, min_length=1, description="Optional skill category.")
    confidence: float | None = Field(
        default=None,
        ge=0,
        le=1,
        description="Confidence that the skill belongs to the candidate.",
    )


class DateRange(BaseModel):
    """Partial date range for education or work history."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    start: str | None = Field(default=None, description="Start date as YYYY or YYYY-MM.")
    end: str | None = Field(default=None, description="End date as YYYY or YYYY-MM.")
    is_current: bool = Field(default=False, description="Whether the date range is currently active.")

    @field_validator("start", "end")
    @classmethod
    def validate_date_part(cls, value: str | None) -> str | None:
        """Validate partial dates while allowing unknown dates."""
        if value is not None and not DATE_PART_PATTERN.match(value):
            raise ValueError("date must use YYYY or YYYY-MM format")
        return value

    @model_validator(mode="after")
    def validate_current_range(self) -> DateRange:
        """Prevent current date ranges from also declaring an end date."""
        if self.is_current and self.end is not None:
            raise ValueError("current date ranges cannot have an end date")
        return self


class ExperienceItem(BaseModel):
    """One normalized work experience entry."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    company: str = Field(..., min_length=1, description="Employer or organization name.")
    title: str | None = Field(default=None, min_length=1, description="Candidate job title.")
    location: Location | None = Field(default=None, description="Work location.")
    date_range: DateRange | None = Field(default=None, description="Employment date range.")
    description: str | None = Field(default=None, min_length=1, description="Role description.")
    skills: list[str] = Field(default_factory=list, description="Skills evidenced by this role.")

    @field_validator("skills")
    @classmethod
    def normalize_skills(cls, value: list[str]) -> list[str]:
        """Trim, deduplicate, and reject blank experience skills."""
        return _normalize_unique_strings(value, "experience skills")


class EducationItem(BaseModel):
    """One normalized education entry."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    institution: str = Field(..., min_length=1, description="School, university, or training provider.")
    degree: str | None = Field(default=None, min_length=1, description="Degree, credential, or qualification.")
    field_of_study: str | None = Field(default=None, min_length=1, description="Primary field of study.")
    location: Location | None = Field(default=None, description="Education location.")
    date_range: DateRange | None = Field(default=None, description="Attendance date range.")


class ProjectItem(BaseModel):
    """One normalized project entry."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(..., min_length=1, description="Project name.")
    description: str | None = Field(default=None, min_length=1, description="Project description.")
    technologies: list[str] = Field(default_factory=list, description="Technologies used by the project.")

    @field_validator("technologies")
    @classmethod
    def normalize_technologies(cls, value: list[str]) -> list[str]:
        """Trim, deduplicate, and reject blank project technologies."""
        return _normalize_unique_strings(value, "project technologies")


class ProvenanceRecord(BaseModel):
    """Origin metadata for a candidate field or record."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    source: Literal["csv", "json", "github", "linkedin", "resume", "manual", "other"] = Field(
        ...,
        description="Source system that supplied the data.",
    )
    field: str | None = Field(default=None, min_length=1, description="Canonical field this provenance applies to.")
    source_record_id: str | None = Field(default=None, min_length=1, description="Identifier in the source system.")
    observed_value: str | None = Field(default=None, description="Original source value before normalization.")
    confidence: float = Field(
        default=1.0,
        ge=0,
        le=1,
        description="Trust score assigned to this source observation.",
    )


class CanonicalCandidate(BaseModel):
    """Canonical, normalized candidate profile used across the application."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    candidate_id: str = Field(..., min_length=1, description="Stable unique identifier for the candidate.")
    full_name: str = Field(..., min_length=1, description="Normalized full name.")
    emails: list[str] = Field(default_factory=list, description="Normalized candidate email addresses.")
    phones: list[str] = Field(default_factory=list, description="Normalized candidate phone numbers.")
    location: Location | None = Field(default=None, description="Best-known candidate location.")
    links: list[CandidateLink] = Field(default_factory=list, description="Candidate profile and contact links.")
    headline: str | None = Field(default=None, min_length=1, description="Short candidate summary or headline.")
    years_experience: float | None = Field(
        default=None,
        ge=0,
        description="Total professional experience in years.",
    )
    skills: list[Skill] = Field(default_factory=list, description="Normalized candidate skills.")
    experience: list[ExperienceItem] = Field(default_factory=list, description="Normalized work history.")
    education: list[EducationItem] = Field(default_factory=list, description="Normalized education history.")
    projects: list[ProjectItem] = Field(default_factory=list, description="Normalized projects.")
    certifications: list[str] = Field(default_factory=list, description="Normalized certifications.")
    resume_summary: str | None = Field(default=None, min_length=1, description="Optional extracted resume summary.")
    provenance: list[ProvenanceRecord] = Field(
        default_factory=list,
        description="Source metadata for fields and records used to create the candidate.",
    )
    overall_confidence: float = Field(
        default=0,
        ge=0,
        le=1,
        description="Overall confidence score for the canonical candidate record.",
    )

    @field_validator("emails")
    @classmethod
    def validate_emails(cls, value: list[str]) -> list[str]:
        """Normalize, deduplicate, and validate email addresses."""
        emails = _normalize_unique_strings(value, "emails", lowercase=True)
        invalid_emails = [email for email in emails if not EMAIL_PATTERN.match(email)]
        if invalid_emails:
            raise ValueError(f"invalid email address: {invalid_emails[0]}")
        return emails

    @field_validator("phones")
    @classmethod
    def validate_phones(cls, value: list[str]) -> list[str]:
        """Normalize, deduplicate, and validate phone numbers."""
        phones = _normalize_unique_strings(value, "phones")
        invalid_phones = [phone for phone in phones if not PHONE_PATTERN.match(phone)]
        if invalid_phones:
            raise ValueError(f"invalid phone number: {invalid_phones[0]}")
        return phones

    @field_validator("skills")
    @classmethod
    def deduplicate_skills(cls, value: list[Skill]) -> list[Skill]:
        """Reject duplicate skill names after case normalization."""
        seen: set[str] = set()
        for skill in value:
            key = skill.name.casefold()
            if key in seen:
                raise ValueError(f"duplicate skill: {skill.name}")
            seen.add(key)
        return value

    @field_validator("links")
    @classmethod
    def deduplicate_links(cls, value: list[CandidateLink]) -> list[CandidateLink]:
        """Reject duplicate candidate links."""
        seen: set[str] = set()
        for link in value:
            key = link.url.casefold()
            if key in seen:
                raise ValueError(f"duplicate link: {link.url}")
            seen.add(key)
        return value

    @field_validator("certifications")
    @classmethod
    def normalize_certifications(cls, value: list[str]) -> list[str]:
        """Trim, deduplicate, and reject blank certifications."""
        return _normalize_unique_strings(value, "certifications")


def _normalize_unique_strings(values: list[str], field_name: str, *, lowercase: bool = False) -> list[str]:
    """Trim, optionally lowercase, and deduplicate a string list."""
    normalized_values: list[str] = []
    seen: set[str] = set()

    for item in values:
        normalized = item.strip()
        if lowercase:
            normalized = normalized.lower()
        if not normalized:
            raise ValueError(f"{field_name} cannot contain blank values")

        key = normalized.casefold()
        if key not in seen:
            normalized_values.append(normalized)
            seen.add(key)

    return normalized_values
