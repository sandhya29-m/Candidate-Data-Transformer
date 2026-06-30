"""Unit tests for configuration loading."""

import json

import pytest

from candidate_transformer.core.config import ConfigurationLoader, MissingValueStrategy
from candidate_transformer.core.exceptions import (
    ConfigurationFileNotFoundError,
    ConfigurationParseError,
    ConfigurationValidationError,
)


def test_loads_valid_configuration(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "output_fields": [
                    {"name": "name", "required": True},
                    {"name": "email"},
                ],
                "field_renaming": {"name": "fullName"},
                "missing_value_strategy": "omit",
                "source_priorities": {"linkedin": 10, "github": 7},
                "use_ai": True,
            }
        ),
        encoding="utf-8",
    )

    config = ConfigurationLoader().load(config_path)

    assert [field.name for field in config.output_fields] == ["name", "email"]
    assert config.field_renaming == {"name": "fullName"}
    assert config.missing_value_strategy is MissingValueStrategy.OMIT
    assert config.source_priorities == {"linkedin": 10, "github": 7}
    assert config.use_ai is True


def test_raises_for_missing_file(tmp_path):
    missing_path = tmp_path / "missing.json"

    with pytest.raises(ConfigurationFileNotFoundError):
        ConfigurationLoader().load(missing_path)


def test_raises_for_invalid_json(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text("{not-json", encoding="utf-8")

    with pytest.raises(ConfigurationParseError):
        ConfigurationLoader().load(config_path)


def test_raises_for_unknown_renamed_field(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "output_fields": [{"name": "email"}],
                "field_renaming": {"name": "fullName"},
                "missing_value_strategy": "keep_null",
                "source_priorities": {"csv": 1},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationValidationError):
        ConfigurationLoader().load(config_path)


def test_raises_for_negative_source_priority(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "output_fields": [{"name": "email"}],
                "source_priorities": {"github": -1},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationValidationError):
        ConfigurationLoader().load(config_path)
