"""Domain models for canonical candidate data."""

from candidate_transformer.domain.candidate import (
    CanonicalCandidate,
    CandidateLink,
    EducationItem,
    ExperienceItem,
    Location,
    ProjectItem,
    ProvenanceRecord,
    Skill,
)
from candidate_transformer.domain.candidate_record import CandidateRecord, RawFieldValue, SourceInfo

__all__ = [
    "CanonicalCandidate",
    "CandidateLink",
    "CandidateRecord",
    "EducationItem",
    "ExperienceItem",
    "Location",
    "ProjectItem",
    "ProvenanceRecord",
    "RawFieldValue",
    "Skill",
    "SourceInfo",
]
