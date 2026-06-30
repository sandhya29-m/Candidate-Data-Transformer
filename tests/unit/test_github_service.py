"""Unit tests for GitHub API service error handling."""

from urllib.error import HTTPError

import pytest

from candidate_transformer.services.github_service import GitHubAPIClient, GitHubAPIError


def test_friendly_rate_limit_error_message():
    error = HTTPError(url="https://api.github.com/users/octocat", code=403, msg="Forbidden", hdrs=None, fp=None)

    message = GitHubAPIClient()._friendly_http_error(error)

    assert "rate limit" in message


def test_friendly_not_found_error_message():
    error = HTTPError(url="https://api.github.com/users/missing", code=404, msg="Not Found", hdrs=None, fp=None)

    message = GitHubAPIClient()._friendly_http_error(error)

    assert "not found" in message


def test_repositories_response_must_be_list(monkeypatch):
    client = GitHubAPIClient()

    monkeypatch.setattr(client, "_get_json", lambda url: {"not": "a list"})

    with pytest.raises(GitHubAPIError, match="repositories response"):
        client.fetch_repositories("octocat")
