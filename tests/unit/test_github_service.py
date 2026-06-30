"""Unit tests for GitHub API service error handling."""

from urllib.error import HTTPError

import pytest

from candidate_transformer.services.github_service import GitHubAPIClient, GitHubAPIError


def test_friendly_rate_limit_error_message():
    error = HTTPError(
        url="https://api.github.com/users/octocat",
        code=403,
        msg="Forbidden",
        hdrs={"X-RateLimit-Remaining": "0"},
        fp=None,
    )

    message = GitHubAPIClient()._friendly_http_error(error)

    assert message == "GitHub API rate limit reached. Configure GITHUB_TOKEN or wait until the limit resets."


def test_friendly_access_denied_error_message():
    error = HTTPError(
        url="https://api.github.com/users/octocat",
        code=403,
        msg="Forbidden",
        hdrs={"X-RateLimit-Remaining": "42"},
        fp=None,
    )

    message = GitHubAPIClient()._friendly_http_error(error)

    assert message == "GitHub authentication failed. Check your Personal Access Token."


def test_friendly_not_found_error_message():
    error = HTTPError(url="https://api.github.com/users/missing", code=404, msg="Not Found", hdrs=None, fp=None)

    message = GitHubAPIClient()._friendly_http_error(error)

    assert "not found" in message


def test_headers_include_auth_only_when_token_exists(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "secret-token")

    headers = GitHubAPIClient()._headers()

    assert headers["Accept"] == "application/vnd.github+json"
    assert headers["User-Agent"] == "candidate-transformer"
    assert headers["X-GitHub-Api-Version"] == "2022-11-28"
    assert headers["Authorization"] == "Bearer secret-token"


def test_headers_omit_auth_when_token_missing(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)

    headers = GitHubAPIClient()._headers()

    assert headers["Accept"] == "application/vnd.github+json"
    assert headers["User-Agent"] == "candidate-transformer"
    assert headers["X-GitHub-Api-Version"] == "2022-11-28"
    assert "Authorization" not in headers


def test_repositories_response_must_be_list(monkeypatch):
    client = GitHubAPIClient()

    monkeypatch.setattr(client, "_get_json", lambda url: {"not": "a list"})

    with pytest.raises(GitHubAPIError, match="repositories response"):
        client.fetch_repositories("octocat")
