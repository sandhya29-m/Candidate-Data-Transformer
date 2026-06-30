"""Unit tests for the canonical candidate schema."""

import pytest
from pydantic import ValidationError

from candidate_transformer.domain.candidate import CanonicalCandidate


def test_valid_candidate_schema_normalizes_contact_lists():
    candidate = CanonicalCandidate(
        candidate_id="cand-001",
        full_name="Ada Lovelace",
        emails=[" ADA@example.com ", "ada@example.com"],
        phones=["+1 555 010 1000"],
        location={"city": "London", "country": "United Kingdom"},
        links=[{"type": "github", "url": "https://github.com/ada"}],
        headline="Backend engineer",
        years_experience=5.5,
        skills=[{"name": "Python", "confidence": 0.95}],
        experience=[
            {
                "company": "Analytical Engines",
                "title": "Engineer",
                "date_range": {"start": "2021-01", "is_current": True},
                "skills": ["Python", " APIs ", "Python"],
            }
        ],
        education=[{"institution": "University of London", "degree": "Mathematics"}],
        provenance=[{"source": "json", "field": "emails", "confidence": 0.9}],
        overall_confidence=0.88,
    )

    assert candidate.emails == ["ada@example.com"]
    assert candidate.experience[0].skills == ["Python", "APIs"]


def test_rejects_invalid_email():
    with pytest.raises(ValidationError):
        CanonicalCandidate(candidate_id="cand-001", full_name="Ada Lovelace", emails=["not-an-email"])


def test_rejects_duplicate_skills():
    with pytest.raises(ValidationError):
        CanonicalCandidate(
            candidate_id="cand-001",
            full_name="Ada Lovelace",
            skills=[{"name": "Python"}, {"name": "python"}],
        )


def test_rejects_confidence_outside_zero_to_one():
    with pytest.raises(ValidationError):
        CanonicalCandidate(
            candidate_id="cand-001",
            full_name="Ada Lovelace",
            overall_confidence=1.5,
        )


def test_rejects_current_date_range_with_end_date():
    with pytest.raises(ValidationError):
        CanonicalCandidate(
            candidate_id="cand-001",
            full_name="Ada Lovelace",
            experience=[
                {
                    "company": "Analytical Engines",
                    "date_range": {"start": "2021", "end": "2024", "is_current": True},
                }
            ],
        )
