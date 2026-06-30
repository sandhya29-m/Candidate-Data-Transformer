"""Unit tests for provenance building."""

from datetime import datetime, timezone

from candidate_transformer.domain import CandidateRecord
from candidate_transformer.provenance import ProvenanceBuilder
from candidate_transformer.scoring import ConfidenceCalculator


def _record(**overrides):
    values = {
        "source": {
            "source_type": "csv",
            "source_name": "recruiter_csv",
            "ingested_at": datetime(2024, 1, 1, tzinfo=timezone.utc),
        },
        "full_name": "Ada Lovelace",
    }
    values.update(overrides)
    return CandidateRecord(**values)


def test_builds_provenance_for_every_supported_field():
    provenance = ProvenanceBuilder().build(_record(emails=["ada@example.com"]))

    assert set(provenance) == set(ProvenanceBuilder.DEFAULT_MERGE_METHODS)
    assert provenance["full_name"]
    assert provenance["emails"]
    assert provenance["phones"] == []


def test_uses_raw_values_as_field_sources():
    record = _record(
        raw_values=[
            {"field_name": "full_name", "source_key": "name", "value": "Ada Lovelace"},
            {"field_name": "emails", "source_key": "email", "value": "ada@example.com"},
        ],
        emails=["ada@example.com"],
    )

    provenance = ProvenanceBuilder().build(record)

    assert provenance["full_name"][0].source == "recruiter_csv"
    assert provenance["full_name"][0].source_key == "name"
    assert provenance["emails"][0].merge_method == "union_deduplicate"


def test_splits_source_qualified_keys_from_merged_records():
    record = _record(
        source={"source_type": "other", "source_name": "merge_engine"},
        emails=["ada@example.com"],
        raw_values=[
            {"field_name": "emails", "source_key": "recruiter_csv:email", "value": "ada@example.com"},
            {"field_name": "emails", "source_key": "linkedin_profile:email", "value": "ada@example.com"},
        ],
        raw_payload={
            "merged_from": [
                {
                    "source": {
                        "source_type": "csv",
                        "source_name": "recruiter_csv",
                        "ingested_at": "2024-01-01T00:00:00+00:00",
                    }
                },
                {
                    "source": {
                        "source_type": "linkedin",
                        "source_name": "linkedin_profile",
                        "ingested_at": "2024-01-02T00:00:00+00:00",
                    }
                },
            ]
        },
    )

    provenance = ProvenanceBuilder().build(record)

    assert [entry.source for entry in provenance["emails"]] == ["recruiter_csv", "linkedin_profile"]
    assert [entry.source_key for entry in provenance["emails"]] == ["email", "email"]
    assert provenance["emails"][1].timestamp == datetime(2024, 1, 2, tzinfo=timezone.utc)


def test_uses_configurable_confidence_and_merge_methods():
    calculator = ConfidenceCalculator(source_weights={"recruiter_csv": 0.25})
    builder = ProvenanceBuilder(
        confidence_calculator=calculator,
        merge_methods={"full_name": "manual_override"},
    )

    provenance = builder.build(_record())

    assert provenance["full_name"][0].confidence == 0.25
    assert provenance["full_name"][0].merge_method == "manual_override"


def test_can_omit_timestamps():
    provenance = ProvenanceBuilder(include_timestamps=False).build(_record())

    assert provenance["full_name"][0].timestamp is None
