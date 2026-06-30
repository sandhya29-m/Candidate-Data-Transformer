"""Source ingestion parsers."""

__all__ = [
    "ATSJSONParser",
    "GitHubAPIClient",
    "GitHubAPIError",
    "GitHubProfileParser",
    "GitHubProfileURLParser",
    "LinkedInParser",
    "RecruiterCSVParser",
]


def __getattr__(name: str):
    """Lazily expose ingestion classes without creating import cycles."""
    if name == "ATSJSONParser":
        from candidate_transformer.ingestion.ats_json_parser import ATSJSONParser

        return ATSJSONParser
    if name == "GitHubProfileParser":
        from candidate_transformer.ingestion.github_profile_parser import GitHubProfileParser

        return GitHubProfileParser
    if name == "GitHubProfileURLParser":
        from candidate_transformer.ingestion.github_url_parser import GitHubProfileURLParser

        return GitHubProfileURLParser
    if name == "LinkedInParser":
        from candidate_transformer.ingestion.linkedin_parser import LinkedInParser

        return LinkedInParser
    if name == "RecruiterCSVParser":
        from candidate_transformer.ingestion.recruiter_csv_parser import RecruiterCSVParser

        return RecruiterCSVParser
    if name in {"GitHubAPIClient", "GitHubAPIError"}:
        from candidate_transformer.services.github_service import GitHubAPIClient, GitHubAPIError

        return {"GitHubAPIClient": GitHubAPIClient, "GitHubAPIError": GitHubAPIError}[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
