"""Unit tests for confidence calculation."""

from candidate_transformer.domain import CandidateRecord
from candidate_transformer.scoring import ConfidenceCalculator


def _record(**overrides):
    values = {
        "source": {"source_type": "csv", "source_name": "recruiter_csv"},
        "full_name": "Ada Lovelace",
    }
    values.update(overrides)
    return CandidateRecord(**values)


def test_assigns_confidence_to_every_configured_field():
    result = ConfidenceCalculator().calculate(_record(emails=["ada@example.com"]))

    assert set(result.field_confidence) == set(ConfidenceCalculator.DEFAULT_FIELD_WEIGHTS)
    assert result.field_confidence["full_name"] > 0
    assert result.field_confidence["emails"] > 0
    assert result.field_confidence["phones"] == 0


def test_uses_configurable_source_weights():
    record = _record(raw_values=[{"field_name": "full_name", "source_key": "recruiter_csv:name", "value": "Ada"}])

    result = ConfidenceCalculator(source_weights={"recruiter_csv": 0.25}).calculate(record)

    assert result.field_confidence["full_name"] == 0.25


def test_combines_multiple_source_evidence_for_a_field():
    record = _record(
        emails=["ada@example.com"],
        raw_values=[
            {"field_name": "emails", "source_key": "recruiter_csv:emails", "value": "ada@example.com"},
            {"field_name": "emails", "source_key": "linkedin_profile:emails", "value": "ada@example.com"},
        ],
    )

    result = ConfidenceCalculator(source_weights={"recruiter_csv": 0.6, "linkedin_profile": 0.9}).calculate(record)

    assert result.field_confidence["emails"] == 0.96


def test_maps_raw_aliases_to_candidate_fields():
    record = _record(
        links=["https://github.com/ada"],
        skills=["Python"],
        raw_values=[
            {"field_name": "github_url", "source_key": "github_profile:html_url", "value": "https://github.com/ada"},
            {"field_name": "languages", "source_key": "github_profile:languages", "value": ["Python"]},
        ],
    )

    result = ConfidenceCalculator(source_weights={"github_profile": 0.8}).calculate(record)

    assert result.field_confidence["links"] == 0.8
    assert result.field_confidence["skills"] == 0.8


def test_calculates_weighted_overall_confidence():
    calculator = ConfidenceCalculator(
        source_weights={"recruiter_csv": 0.5},
        field_weights={"full_name": 1.0, "emails": 1.0},
    )
    record = _record(emails=["ada@example.com"])

    result = calculator.calculate(record)

    assert 0 < result.overall_confidence < 1
    assert result.overall_confidence == 0.5


def test_uses_merged_payload_as_fallback_evidence():
    record = _record(
        source={"source_type": "other", "source_name": "merge_engine"},
        emails=["ada@example.com"],
        raw_payload={
            "merged_from": [
                {"source": {"source_type": "csv", "source_name": "recruiter_csv"}},
                {"source": {"source_type": "linkedin", "source_name": "linkedin_profile"}},
            ]
        },
    )

    result = ConfidenceCalculator(source_weights={"recruiter_csv": 0.6, "linkedin_profile": 0.9}).calculate(record)

    assert result.field_confidence["emails"] == 0.96
