"""Unit tests for the recruiter CSV parser."""

import pandas as pd
import pytest

from candidate_transformer.ingestion.exceptions import (
    ParserFileNotFoundError,
    ParserSchemaError,
    ParserValidationError,
)
from candidate_transformer.ingestion.recruiter_csv_parser import RecruiterCSVParser


def test_parser_converts_csv_rows_to_candidate_records(tmp_path):
    csv_path = tmp_path / "candidates.csv"
    pd.DataFrame(
        [
            {
                "candidate_id": "cand-1",
                "full_name": "Ada Lovelace",
                "emails": "ada@example.com,work@example.com",
                "phones": "+1 555 010 1000",
                "location": "London",
                "links": "https://example.com/ada",
                "headline": "Backend engineer",
                "years_experience": "5.5",
                "skills": "Python,APIs",
                "experience": "Engineer at Analytical Engines",
                "education": "Mathematics",
            }
        ]
    ).to_csv(csv_path, index=False)

    records = RecruiterCSVParser().parse(csv_path)

    assert len(records) == 1
    assert records[0].source.source_type == "csv"
    assert records[0].external_id == "cand-1"
    assert records[0].full_name == "Ada Lovelace"
    assert records[0].emails == ["ada@example.com", "work@example.com"]
    assert records[0].skills == ["Python", "APIs"]
    assert records[0].experience == [{"raw": "Engineer at Analytical Engines"}]
    assert records[0].raw_payload["row_number"] == 2


def test_parser_handles_missing_values(tmp_path):
    csv_path = tmp_path / "candidates.csv"
    pd.DataFrame([{"candidate_id": "cand-1", "full_name": "", "emails": ""}]).to_csv(csv_path, index=False)

    records = RecruiterCSVParser().parse(csv_path)

    assert records[0].external_id == "cand-1"
    assert records[0].full_name is None
    assert records[0].emails == []


def test_parser_supports_common_recruiter_columns(tmp_path):
    csv_path = tmp_path / "candidates.csv"
    pd.DataFrame(
        [
            {
                "name": "Alice Johnson",
                "email": "alice@example.com",
                "phone": "+1 415 555 2671",
                "current_company": "Google",
                "title": "Staff Engineer",
                "github_url": "https://github.com/alice",
            }
        ]
    ).to_csv(csv_path, index=False)

    record = RecruiterCSVParser().parse(csv_path)[0]

    assert record.full_name == "Alice Johnson"
    assert record.emails == ["alice@example.com"]
    assert record.phones == ["+1 415 555 2671"]
    assert record.links == ["https://github.com/alice"]
    assert record.headline == "Staff Engineer"
    assert record.experience == [{"company": "Google", "title": "Staff Engineer"}]


def test_parser_skips_invalid_rows(tmp_path):
    csv_path = tmp_path / "candidates.csv"
    pd.DataFrame(
        [
            {"candidate_id": "cand-1", "full_name": "Ada Lovelace", "years_experience": "4"},
            {"candidate_id": "cand-2", "full_name": "Grace Hopper", "years_experience": "-2"},
        ]
    ).to_csv(csv_path, index=False)

    records = RecruiterCSVParser().parse(csv_path)

    assert len(records) == 1
    assert records[0].external_id == "cand-1"


def test_parser_skips_rows_with_non_numeric_years_experience(tmp_path):
    csv_path = tmp_path / "candidates.csv"
    pd.DataFrame(
        [
            {"candidate_id": "cand-1", "full_name": "Ada Lovelace", "years_experience": "4"},
            {"candidate_id": "cand-2", "full_name": "Grace Hopper", "years_experience": "senior"},
        ]
    ).to_csv(csv_path, index=False)

    records = RecruiterCSVParser().parse(csv_path)

    assert len(records) == 1
    assert records[0].external_id == "cand-1"


def test_parser_raises_when_file_missing(tmp_path):
    with pytest.raises(ParserFileNotFoundError):
        RecruiterCSVParser().parse(tmp_path / "missing.csv")


def test_parser_raises_when_no_identifying_columns(tmp_path):
    csv_path = tmp_path / "candidates.csv"
    pd.DataFrame([{"notes": "not enough"}]).to_csv(csv_path, index=False)

    with pytest.raises(ParserSchemaError):
        RecruiterCSVParser().parse(csv_path)


def test_parser_raises_when_all_rows_invalid(tmp_path):
    csv_path = tmp_path / "candidates.csv"
    pd.DataFrame([{"candidate_id": "cand-1", "years_experience": "-1"}]).to_csv(csv_path, index=False)

    with pytest.raises(ParserValidationError):
        RecruiterCSVParser().parse(csv_path)
