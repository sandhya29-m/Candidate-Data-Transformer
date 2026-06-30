"""Unit tests for the LinkedIn parser."""

import json

import pytest

from candidate_transformer.ingestion.exceptions import (
    ParserFileNotFoundError,
    ParserSchemaError,
    ParserValidationError,
)
from candidate_transformer.ingestion.linkedin_parser import LinkedInParser


def test_parser_extracts_linkedin_profile_fields(tmp_path):
    json_path = tmp_path / "linkedin.json"
    json_path.write_text(
        json.dumps(
            {
                "profile": {
                    "name": "Ada Lovelace",
                    "headline": "Backend engineer",
                    "profile_url": "https://www.linkedin.com/in/ada",
                    "experience": [{"company": "Analytical Engines", "title": "Engineer"}],
                    "education": [{"school": "University of London"}],
                    "skills": [{"name": "Python"}, {"name": "APIs"}],
                }
            }
        ),
        encoding="utf-8",
    )

    records = LinkedInParser().parse(json_path)

    assert len(records) == 1
    assert records[0].source.source_type == "linkedin"
    assert records[0].external_id == "https://www.linkedin.com/in/ada"
    assert records[0].full_name == "Ada Lovelace"
    assert records[0].headline == "Backend engineer"
    assert records[0].links == ["https://www.linkedin.com/in/ada"]
    assert records[0].experience == [{"company": "Analytical Engines", "title": "Engineer"}]
    assert records[0].education == [{"school": "University of London"}]
    assert records[0].skills == ["Python", "APIs"]


def test_parser_handles_missing_optional_fields(tmp_path):
    json_path = tmp_path / "linkedin.json"
    json_path.write_text(json.dumps({"name": "Grace Hopper"}), encoding="utf-8")

    record = LinkedInParser().parse(json_path)[0]

    assert record.full_name == "Grace Hopper"
    assert record.headline is None
    assert record.links == []
    assert record.experience == []
    assert record.education == []
    assert record.skills == []


def test_parser_supports_alternate_field_names(tmp_path):
    json_path = tmp_path / "linkedin.json"
    json_path.write_text(
        json.dumps(
            {
                "linkedin_profile": {
                    "fullName": "Katherine Johnson",
                    "title": "Mathematician",
                    "linkedin_url": "https://www.linkedin.com/in/katherine",
                    "positions": ["NASA"],
                    "schools": ["West Virginia State College"],
                    "skill_names": ["Mathematics"],
                }
            }
        ),
        encoding="utf-8",
    )

    record = LinkedInParser().parse(json_path)[0]

    assert record.full_name == "Katherine Johnson"
    assert record.headline == "Mathematician"
    assert record.links == ["https://www.linkedin.com/in/katherine"]
    assert record.experience == [{"raw": "NASA"}]
    assert record.education == [{"raw": "West Virginia State College"}]
    assert record.skills == ["Mathematics"]


def test_parser_preserves_raw_values_and_payload(tmp_path):
    json_path = tmp_path / "linkedin.json"
    json_path.write_text(json.dumps({"name": "Ada Lovelace", "skills": ["Python"]}), encoding="utf-8")

    record = LinkedInParser().parse(json_path)[0]
    raw_values = [item.model_dump() for item in record.raw_values]

    assert {"field_name": "name", "source_key": "name", "value": "Ada Lovelace"} in raw_values
    assert {"field_name": "skills", "source_key": "skills", "value": ["Python"]} in raw_values
    assert record.raw_payload["profile"]["name"] == "Ada Lovelace"


def test_parser_raises_when_file_missing(tmp_path):
    with pytest.raises(ParserFileNotFoundError):
        LinkedInParser().parse(tmp_path / "missing.json")


def test_parser_raises_for_invalid_json(tmp_path):
    json_path = tmp_path / "linkedin.json"
    json_path.write_text("{not-json", encoding="utf-8")

    with pytest.raises(ParserSchemaError):
        LinkedInParser().parse(json_path)


def test_parser_raises_when_profile_has_no_candidate_signal(tmp_path):
    json_path = tmp_path / "linkedin.json"
    json_path.write_text(json.dumps({"profile": {}}), encoding="utf-8")

    with pytest.raises(ParserValidationError):
        LinkedInParser().parse(json_path)
