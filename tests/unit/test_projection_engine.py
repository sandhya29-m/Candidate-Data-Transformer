"""Unit tests for output projection."""

import json

from candidate_transformer.domain import CanonicalCandidate, Skill
from candidate_transformer.output import ProjectionEngine


def _candidate():
    return CanonicalCandidate(
        candidate_id="cand-1",
        full_name="Ada Lovelace",
        emails=["ada@example.com"],
        phones=["+14155552671"],
        location={"city": "London", "country": "United Kingdom"},
        links=[{"type": "github", "url": "https://github.com/ada"}],
        headline="Backend engineer",
        skills=[{"name": "Python"}],
        overall_confidence=0.9,
    )


def test_projects_selected_fields():
    projected = ProjectionEngine().project(
        _candidate(),
        {
            "output_fields": [{"name": "candidate_id"}, {"name": "full_name"}, {"name": "emails"}],
        },
    )

    assert projected == {
        "candidate_id": "cand-1",
        "full_name": "Ada Lovelace",
        "emails": ["ada@example.com"],
    }


def test_applies_field_renaming():
    projected = ProjectionEngine().project(
        _candidate(),
        {
            "output_fields": [{"name": "candidate_id"}, {"name": "full_name"}],
            "field_renaming": {"candidate_id": "id", "full_name": "name"},
        },
    )

    assert projected == {"id": "cand-1", "name": "Ada Lovelace"}


def test_omits_missing_values():
    candidate = _candidate().model_copy(update={"headline": None})

    projected = ProjectionEngine().project(
        candidate,
        {
            "output_fields": [{"name": "full_name"}, {"name": "headline"}],
            "missing_value_strategy": "omit",
        },
    )

    assert projected == {"full_name": "Ada Lovelace"}


def test_keeps_null_missing_values_by_default():
    candidate = _candidate().model_copy(update={"headline": None})

    projected = ProjectionEngine().project(
        candidate,
        {
            "output_fields": [{"name": "headline"}],
        },
    )

    assert projected == {"headline": None}


def test_replaces_missing_values_with_empty_string():
    candidate = _candidate().model_copy(update={"headline": None, "emails": []})

    projected = ProjectionEngine().project(
        candidate,
        {
            "output_fields": [{"name": "headline"}, {"name": "emails"}],
            "missing_value_strategy": "empty_string",
        },
    )

    assert projected == {"headline": "", "emails": ""}


def test_optionally_normalizes_supported_fields():
    candidate = _candidate().model_copy(
        update={
            "emails": [" ADA@EXAMPLE.COM "],
            "phones": ["(415) 555-2671"],
            "skills": [Skill(name="Py"), Skill(name="JS")],
        }
    )

    projected = ProjectionEngine().project(
        candidate,
        {
            "output_fields": [{"name": "emails"}, {"name": "phones"}, {"name": "skills"}],
            "apply_normalization": True,
        },
    )

    assert projected == {
        "emails": ["ada@example.com"],
        "phones": ["+14155552671"],
        "skills": ["Python", "JavaScript"],
    }


def test_accepts_config_json_path(tmp_path):
    config_path = tmp_path / "output_config.json"
    config_path.write_text(
        json.dumps({"output_fields": [{"name": "candidate_id"}, {"name": "overall_confidence"}]}),
        encoding="utf-8",
    )

    projected = ProjectionEngine().project(_candidate(), config_path)

    assert projected == {"candidate_id": "cand-1", "overall_confidence": 0.9}
