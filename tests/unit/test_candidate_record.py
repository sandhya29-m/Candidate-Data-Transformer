"""Unit tests for parser-level candidate records."""

import pytest
from pydantic import ValidationError

from candidate_transformer.domain.candidate_record import CandidateRecord


def test_candidate_record_accepts_common_parser_fields():
    record = CandidateRecord(
        source={
            "source_type": "github",
            "source_name": "GitHub API",
            "source_record_id": "octocat",
            "source_uri": "https://api.github.com/users/octocat",
        },
        external_id="octocat",
        full_name="The Octocat",
        emails=["octo@example.com", " octo@example.com "],
        phones=["+1 555 010 1000"],
        location="San Francisco, CA",
        links=["https://github.com/octocat"],
        headline="Open source contributor",
        years_experience=8,
        skills=["Python", "python", "APIs"],
        experience=[{"company": "GitHub", "title": "Mascot"}],
        education=[{"institution": "Mona University"}],
        raw_values=[{"field_name": "full_name", "source_key": "name", "value": "The Octocat"}],
        raw_payload={"login": "octocat", "name": "The Octocat"},
    )

    assert record.emails == ["octo@example.com"]
    assert record.skills == ["Python", "APIs"]
    assert record.source.source_type == "github"


def test_candidate_record_requires_source_information():
    with pytest.raises(ValidationError):
        CandidateRecord(full_name="Ada Lovelace")


def test_candidate_record_requires_identifying_signal():
    with pytest.raises(ValidationError):
        CandidateRecord(source={"source_type": "csv"})


def test_candidate_record_rejects_blank_list_values():
    with pytest.raises(ValidationError):
        CandidateRecord(source={"source_type": "csv"}, emails=[" "])


def test_candidate_record_rejects_negative_years_experience():
    with pytest.raises(ValidationError):
        CandidateRecord(
            source={"source_type": "linkedin"},
            full_name="Ada Lovelace",
            years_experience=-1,
        )
