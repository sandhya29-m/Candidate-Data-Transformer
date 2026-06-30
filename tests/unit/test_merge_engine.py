"""Unit tests for candidate record merging."""

from datetime import datetime, timezone

import pytest

from candidate_transformer.domain import CandidateRecord
from candidate_transformer.merging import MergeEngine, MergeError


def _record(source_type, *, source_name=None, source_record_id=None, ingested_at=None, **overrides):
    values = {
        "source": {
            "source_type": source_type,
            "source_name": source_name,
            "source_record_id": source_record_id,
            "ingested_at": ingested_at or datetime(2024, 1, 1, tzinfo=timezone.utc),
        },
        "full_name": "Ada Lovelace",
    }
    values.update(overrides)
    return CandidateRecord(**values)


def test_merge_prefers_highest_priority_scalar_values():
    csv_record = _record("csv", full_name="Ada L.", headline="CSV headline")
    linkedin_record = _record("linkedin", full_name="Ada Lovelace", headline="LinkedIn headline")

    merged = MergeEngine({"linkedin": 10, "csv": 1}).merge([csv_record, linkedin_record])

    assert merged.full_name == "Ada Lovelace"
    assert merged.headline == "LinkedIn headline"


def test_merge_removes_duplicate_string_values():
    first = _record("csv", emails=["ada@example.com"], skills=["Python", "APIs"])
    second = _record("linkedin", emails=[" ADA@example.com "], skills=["python", "Leadership"])

    merged = MergeEngine({"linkedin": 10, "csv": 1}).merge([first, second])

    assert merged.emails == ["ADA@example.com"]
    assert merged.skills == ["python", "Leadership", "APIs"]


def test_merge_removes_duplicate_dict_values():
    first = _record("csv", experience=[{"company": "Analytical Engines"}])
    second = _record("linkedin", experience=[{"company": "Analytical Engines"}, {"company": "OpenAI"}])

    merged = MergeEngine({"linkedin": 10, "csv": 1}).merge([first, second])

    assert merged.experience == [{"company": "Analytical Engines"}, {"company": "OpenAI"}]


def test_merge_preserves_provenance():
    csv_record = _record(
        "csv",
        source_name="recruiter_csv",
        raw_values=[{"field_name": "full_name", "source_key": "name", "value": "Ada L."}],
        raw_payload={"row_number": 2},
    )
    linkedin_record = _record(
        "linkedin",
        source_name="linkedin_profile",
        raw_values=[{"field_name": "headline", "source_key": "headline", "value": "Engineer"}],
        raw_payload={"profile": {"headline": "Engineer"}},
    )

    merged = MergeEngine({"linkedin": 10, "csv": 1}).merge([csv_record, linkedin_record])

    raw_values = [item.model_dump() for item in merged.raw_values]
    assert {"field_name": "headline", "source_key": "linkedin_profile:headline", "value": "Engineer"} in raw_values
    assert {"field_name": "full_name", "source_key": "recruiter_csv:name", "value": "Ada L."} in raw_values
    assert [item["source"]["source_type"] for item in merged.raw_payload["merged_from"]] == ["linkedin", "csv"]


def test_merge_output_is_deterministic_for_input_order():
    low_priority = _record("csv", source_record_id="2", full_name="Ada CSV", emails=["csv@example.com"])
    high_priority = _record("linkedin", source_record_id="1", full_name="Ada LinkedIn", emails=["linkedin@example.com"])
    priorities = {"linkedin": 10, "csv": 1}

    first = MergeEngine(priorities).merge([low_priority, high_priority])
    second = MergeEngine(priorities).merge([high_priority, low_priority])

    assert first.model_dump(mode="json") == second.model_dump(mode="json")


def test_merge_raises_for_empty_input():
    with pytest.raises(MergeError):
        MergeEngine().merge([])
