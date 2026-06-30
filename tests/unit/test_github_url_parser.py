"""Unit tests for GitHub profile URL parsing."""

import pytest

from candidate_transformer.ingestion.exceptions import ParserSchemaError
from candidate_transformer.ingestion.github_url_parser import GitHubAPIError, GitHubProfileURLParser


class FakeGitHubClient:
    """GitHub API client test double."""

    def __init__(self, *, fail: bool = False):
        self.fail = fail
        self.profile_username = None
        self.repositories_username = None

    def fetch_profile(self, username):
        self.profile_username = username
        if self.fail:
            raise GitHubAPIError("GitHub API rate limit reached or access was denied. Please wait and try again.")
        return {
            "login": username,
            "name": "The Octocat",
            "bio": "GitHub mascot",
            "company": "GitHub",
            "location": "San Francisco",
            "blog": "https://octocat.example.com",
            "html_url": f"https://github.com/{username}",
        }

    def fetch_repositories(self, username):
        self.repositories_username = username
        return [
            {
                "name": "hello-world",
                "full_name": f"{username}/hello-world",
                "html_url": f"https://github.com/{username}/hello-world",
                "description": "Example repository",
                "language": "Python",
                "stargazers_count": 10,
                "forks_count": 2,
                "updated_at": "2024-01-01T00:00:00Z",
            },
            {
                "name": "api-demo",
                "full_name": f"{username}/api-demo",
                "html_url": f"https://github.com/{username}/api-demo",
                "description": None,
                "language": "JavaScript",
                "stargazers_count": 5,
                "forks_count": 1,
                "updated_at": "2024-01-02T00:00:00Z",
            },
        ]


def test_extracts_username_from_github_profile_url():
    parser = GitHubProfileURLParser(client=FakeGitHubClient())

    assert parser.extract_username("https://github.com/octocat") == "octocat"
    assert parser.extract_username("https://www.github.com/octocat/") == "octocat"


def test_rejects_non_github_urls():
    parser = GitHubProfileURLParser(client=FakeGitHubClient())

    with pytest.raises(ParserSchemaError):
        parser.extract_username("https://example.com/octocat")


def test_rejects_github_url_without_username():
    parser = GitHubProfileURLParser(client=FakeGitHubClient())

    with pytest.raises(ParserSchemaError):
        parser.extract_username("https://github.com/")


def test_fetches_github_profile_and_repositories_into_candidate_record():
    client = FakeGitHubClient()
    parser = GitHubProfileURLParser(client=client)

    record = parser.parse("https://github.com/octocat")[0]

    assert client.profile_username == "octocat"
    assert client.repositories_username == "octocat"
    assert record.source.source_type == "github"
    assert record.external_id == "octocat"
    assert record.full_name == "The Octocat"
    assert record.headline == "GitHub mascot"
    assert record.location == "San Francisco"
    assert record.links == ["https://github.com/octocat", "https://octocat.example.com"]
    assert record.skills == ["Python", "JavaScript"]
    assert record.experience[0]["name"] == "hello-world"


def test_preserves_github_raw_values():
    record = GitHubProfileURLParser(client=FakeGitHubClient()).parse("https://github.com/octocat")[0]
    raw_values = [item.model_dump() for item in record.raw_values]

    assert {"field_name": "company", "source_key": "company", "value": "GitHub"} in raw_values
    assert {"field_name": "languages", "source_key": "repositories.language", "value": ["Python", "JavaScript"]} in raw_values


def test_github_api_failures_are_friendly():
    parser = GitHubProfileURLParser(client=FakeGitHubClient(fail=True))

    with pytest.raises(GitHubAPIError, match="rate limit"):
        parser.parse("https://github.com/octocat")
