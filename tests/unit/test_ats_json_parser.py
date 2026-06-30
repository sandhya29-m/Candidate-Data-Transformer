"""Unit tests for the ATS JSON parser."""

import json

import pytest

from candidate_transformer.ingestion.ats_json_parser import ATSJSONFieldMapping, ATSJSONParser
from candidate_transformer.ingestion.exceptions import (
    ParserFileNotFoundError,
    ParserSchemaError,
    ParserValidationError,
)


def test_parser_maps_nested_ats_json_to_candidate_records(tmp_path):
    json_path = tmp_path / "ats.json"
    json_path.write_text(
        json.dumps(
            {
                "candidates": [
                    {
                        "id": "ats-1",
                        "profile": {
                            "full_name": "Ada Lovelace",
                            "headline": "Backend engineer",
                            "years_experience": "5.5",
                            "skills": [{"name": "Python"}, {"name": "APIs"}],
                        },
                        "contact": {
                            "emails": [{"email": "ada@example.com"}],
                            "phones": [{"phone": "+1 555 010 1000"}],
                        },
                        "address": {"formatted": "London"},
                        "social": {"links": [{"url": "https://example.com/ada"}]},
                        "employment_history": [{"company": "Analytical Engines"}],
                        "education_history": [{"institution": "University of London"}],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    records = ATSJSONParser().parse(json_path)

    assert len(records) == 1
    assert records[0].source.source_type == "json"
    assert records[0].external_id == "ats-1"
    assert records[0].full_name == "Ada Lovelace"
    assert records[0].emails == ["ada@example.com"]
    assert records[0].phones == ["+1 555 010 1000"]
    assert records[0].location == "London"
    assert records[0].links == ["https://example.com/ada"]
    assert records[0].skills == ["Python", "APIs"]
    assert records[0].experience == [{"company": "Analytical Engines"}]
    assert records[0].education == [{"institution": "University of London"}]
    assert records[0].raw_payload["record_index"] == 1


def test_parser_handles_missing_fields(tmp_path):
    json_path = tmp_path / "ats.json"
    json_path.write_text(json.dumps({"candidates": [{"id": "ats-1"}]}), encoding="utf-8")

    records = ATSJSONParser().parse(json_path)

    assert records[0].external_id == "ats-1"
    assert records[0].full_name is None
    assert records[0].emails == []
    assert records[0].skills == []


def test_parser_supports_custom_nested_mapping(tmp_path):
    json_path = tmp_path / "ats.json"
    json_path.write_text(
        json.dumps({"results": [{"uuid": "ats-1", "person": {"display": "Grace Hopper"}}]}),
        encoding="utf-8",
    )
    mapping = ATSJSONFieldMapping(
        records_path="results",
        external_id=("uuid",),
        full_name=("person.display",),
    )

    records = ATSJSONParser(field_mapping=mapping).parse(json_path)

    assert records[0].external_id == "ats-1"
    assert records[0].full_name == "Grace Hopper"


def test_parser_preserves_raw_mapped_values(tmp_path):
    json_path = tmp_path / "ats.json"
    json_path.write_text(
        json.dumps({"candidates": [{"id": "ats-1", "profile": {"full_name": "Ada Lovelace"}}]}),
        encoding="utf-8",
    )

    record = ATSJSONParser().parse(json_path)[0]

    assert {"field_name": "external_id", "source_key": "id", "value": "ats-1"} in [
        item.model_dump() for item in record.raw_values
    ]
    assert record.raw_payload["payload"]["profile"]["full_name"] == "Ada Lovelace"


def test_parser_raises_when_file_missing(tmp_path):
    with pytest.raises(ParserFileNotFoundError):
        ATSJSONParser().parse(tmp_path / "missing.json")


def test_parser_raises_for_invalid_json(tmp_path):
    json_path = tmp_path / "ats.json"
    json_path.write_text("{not-json", encoding="utf-8")

    with pytest.raises(ParserSchemaError):
        ATSJSONParser().parse(json_path)


def test_parser_raises_when_all_records_invalid(tmp_path):
    json_path = tmp_path / "ats.json"
    json_path.write_text(json.dumps({"candidates": [{"years_experience": "-1"}]}), encoding="utf-8")

    with pytest.raises(ParserValidationError):
        ATSJSONParser().parse(json_path)
