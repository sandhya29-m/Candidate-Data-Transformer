"""Unit tests for the GitHub profile parser."""

import json

import pytest

from candidate_transformer.ingestion.exceptions import (
    ParserFileNotFoundError,
    ParserSchemaError,
    ParserValidationError,
)
from candidate_transformer.ingestion.github_profile_parser import GitHubProfileParser


def test_parser_extracts_github_profile_fields(tmp_path):
    json_path = tmp_path / "github.json"
    json_path.write_text(
        json.dumps(
            {
                "profile": {
                    "login": "octocat",
                    "html_url": "https://github.com/octocat",
                    "name": "The Octocat",
                    "bio": "GitHub mascot",
                    "location": "San Francisco",
                    "languages": ["Ruby"],
                },
                "repositories": [
                    {"name": "hello-world", "html_url": "https://github.com/octocat/hello-world", "language": "Python"},
                    {"name": "api-demo", "language": "Go"},
                ],
            }
        ),
        encoding="utf-8",
    )

    records = GitHubProfileParser().parse(json_path)

    assert len(records) == 1
    assert records[0].source.source_type == "github"
    assert records[0].external_id == "octocat"
    assert records[0].full_name == "The Octocat"
    assert records[0].links == ["https://github.com/octocat"]
    assert records[0].headline == "GitHub mascot"
    assert records[0].skills == ["Ruby", "Python", "Go"]
    assert records[0].experience[0]["name"] == "hello-world"
    assert records[0].raw_payload["repositories"][1]["name"] == "api-demo"


def test_parser_builds_github_url_from_username(tmp_path):
    json_path = tmp_path / "github.json"
    json_path.write_text(json.dumps({"login": "octocat", "bio": "GitHub mascot"}), encoding="utf-8")

    record = GitHubProfileParser().parse(json_path)[0]

    assert record.external_id == "octocat"
    assert record.links == ["https://github.com/octocat"]


def test_parser_handles_missing_optional_fields(tmp_path):
    json_path = tmp_path / "github.json"
    json_path.write_text(json.dumps({"login": "octocat"}), encoding="utf-8")

    record = GitHubProfileParser().parse(json_path)[0]

    assert record.headline is None
    assert record.skills == []
    assert record.experience == []


def test_parser_preserves_raw_values(tmp_path):
    json_path = tmp_path / "github.json"
    json_path.write_text(
        json.dumps({"login": "octocat", "repositories": [{"name": "hello-world", "language": "Python"}]}),
        encoding="utf-8",
    )

    record = GitHubProfileParser().parse(json_path)[0]
    raw_values = [item.model_dump() for item in record.raw_values]

    assert {"field_name": "username", "source_key": "login", "value": "octocat"} in raw_values
    assert {"field_name": "languages", "source_key": "languages/repositories.language", "value": ["Python"]} in raw_values


def test_parser_raises_when_file_missing(tmp_path):
    with pytest.raises(ParserFileNotFoundError):
        GitHubProfileParser().parse(tmp_path / "missing.json")


def test_parser_raises_for_invalid_json(tmp_path):
    json_path = tmp_path / "github.json"
    json_path.write_text("{not-json", encoding="utf-8")

    with pytest.raises(ParserSchemaError):
        GitHubProfileParser().parse(json_path)


def test_parser_raises_when_profile_has_no_candidate_signal(tmp_path):
    json_path = tmp_path / "github.json"
    json_path.write_text(json.dumps({"repositories": []}), encoding="utf-8")

    with pytest.raises(ParserValidationError):
        GitHubProfileParser().parse(json_path)
