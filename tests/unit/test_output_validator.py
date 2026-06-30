"""Unit tests for projected output validation."""

from datetime import datetime

from candidate_transformer.output import OutputValidator


def test_validates_projected_json_successfully():
    result = OutputValidator().validate(
        {"id": "cand-1", "name": "Ada Lovelace"},
        {
            "output_fields": [{"name": "candidate_id", "required": True}, {"name": "full_name"}],
            "field_renaming": {"candidate_id": "id", "full_name": "name"},
        },
    )

    assert result.is_valid is True
    assert result.errors == []


def test_reports_missing_required_field():
    result = OutputValidator().validate(
        {"name": "Ada Lovelace"},
        {
            "output_fields": [{"name": "candidate_id", "required": True}, {"name": "full_name"}],
            "field_renaming": {"candidate_id": "id", "full_name": "name"},
        },
    )

    assert result.is_valid is False
    assert any(error.field == "id" and error.error_type == "missing" for error in result.errors)


def test_reports_empty_required_field_meaningfully():
    result = OutputValidator().validate(
        {"id": "", "name": "Ada Lovelace"},
        {
            "output_fields": [{"name": "candidate_id", "required": True}, {"name": "full_name"}],
            "field_renaming": {"candidate_id": "id", "full_name": "name"},
        },
    )

    assert result.is_valid is False
    assert any(error.field == "id" and error.error_type == "required_missing" for error in result.errors)


def test_reports_unexpected_fields():
    result = OutputValidator().validate(
        {"candidate_id": "cand-1", "unexpected": True},
        {"output_fields": [{"name": "candidate_id"}]},
    )

    assert result.is_valid is False
    assert any(error.field == "unexpected" and error.error_type == "extra_forbidden" for error in result.errors)


def test_reports_non_json_object_without_crashing():
    result = OutputValidator().validate(
        ["not", "an", "object"],
        {"output_fields": [{"name": "candidate_id"}]},
    )

    assert result.is_valid is False
    assert result.errors[0].error_type == "invalid_root_type"


def test_reports_non_json_serializable_values_without_crashing():
    result = OutputValidator().validate(
        {"candidate_id": "cand-1", "created_at": datetime(2024, 1, 1)},
        {"output_fields": [{"name": "candidate_id"}, {"name": "created_at"}]},
    )

    assert result.is_valid is False
    assert any(error.error_type == "not_json_serializable" for error in result.errors)


def test_invalid_config_returns_validation_result_instead_of_raising():
    result = OutputValidator().validate(
        {"candidate_id": "cand-1"},
        {"output_fields": []},
    )

    assert result.is_valid is False
    assert result.errors[0].error_type == "validator_error"
