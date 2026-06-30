"""Unit tests for candidate matching."""

from candidate_transformer.domain import CandidateRecord
from candidate_transformer.matching import CandidateMatcher


def _record(**overrides):
    values = {
        "source": {"source_type": "manual"},
        "full_name": "Ada Lovelace",
    }
    values.update(overrides)
    return CandidateRecord(**values)


def test_matches_by_email_first():
    result = CandidateMatcher().match(
        _record(emails=["Ada@Example.com"], phones=["+1 415 555 2671"]),
        _record(full_name="Different Person", emails=[" ada@example.com "], phones=["+1 999 555 0000"]),
    )

    assert result.is_match is True
    assert result.confidence == 1.0
    assert result.reason.startswith("Email matched")


def test_matches_by_phone_when_email_missing():
    result = CandidateMatcher().match(
        _record(phones=["+1 (415) 555-2671"]),
        _record(full_name="Different Person", phones=["+14155552671"]),
    )

    assert result.is_match is True
    assert result.confidence == 0.98
    assert result.reason == "Phone number matched"


def test_matches_phone_after_e164_normalization():
    result = CandidateMatcher().match(
        _record(phones=["415 555 2671"]),
        _record(full_name="Different Person", phones=["+14155552671"]),
    )

    assert result.is_match is True
    assert result.reason == "Phone number matched"


def test_matches_by_linkedin_url():
    result = CandidateMatcher().match(
        _record(links=["https://www.linkedin.com/in/ada/"]),
        _record(full_name="Different Person", links=["https://linkedin.com/in/ada"]),
    )

    assert result.is_match is True
    assert result.reason == "LinkedIn URL matched"


def test_matches_by_github_url():
    result = CandidateMatcher().match(
        _record(links=["https://github.com/ada"]),
        _record(full_name="Different Person", links=["https://www.github.com/ada/"]),
    )

    assert result.is_match is True
    assert result.reason == "GitHub URL matched"


def test_matches_by_github_url_from_source_uri():
    result = CandidateMatcher().match(
        _record(links=["https://github.com/sandhya-m"]),
        _record(
            source={"source_type": "github", "source_name": "github_api", "source_uri": "https://github.com/sandhya-m"},
            full_name="Different Person",
        ),
    )

    assert result.is_match is True
    assert result.reason == "GitHub URL matched"


def test_matches_by_name_similarity():
    result = CandidateMatcher().match(
        _record(full_name="Ada Lovelace"),
        _record(full_name="Lovelace, Ada"),
    )

    assert result.is_match is True
    assert result.reason.startswith("Name similarity matched")


def test_matches_name_with_initial_against_expanded_name():
    result = CandidateMatcher().match(
        _record(full_name="SANDHYA M"),
        _record(full_name="Sandhya Muruganand"),
    )

    assert result.is_match is True
    assert result.reason.startswith("Name similarity matched")


def test_matches_by_name_and_company_when_name_alone_is_lower():
    matcher = CandidateMatcher(name_similarity_threshold=99, name_company_similarity_threshold=80)

    result = matcher.match(
        _record(full_name="Ada B", experience=[{"company": "Analytical Engines"}]),
        _record(full_name="Ada Byron Lovelace", experience=[{"employer": "Analytical Engine"}]),
    )

    assert result.is_match is True
    assert result.reason.startswith("Name and company matched")


def test_matches_by_name_and_skills_when_names_are_close():
    matcher = CandidateMatcher(name_similarity_threshold=99, name_skills_similarity_threshold=80)

    result = matcher.match(
        _record(full_name="Sandhya M", skills=["Python", "Machine Learning"]),
        _record(full_name="Sandhya Muruganand", skills=["python", "SQL"]),
    )

    assert result.is_match is True
    assert result.reason.startswith("Name and skills matched")


def test_does_not_match_similar_name_without_supporting_signals():
    matcher = CandidateMatcher(name_similarity_threshold=99, name_company_similarity_threshold=95, name_skills_similarity_threshold=95)

    result = matcher.match(
        _record(full_name="Alex Kim", skills=["Python"]),
        _record(full_name="Alex King", skills=["Java"]),
    )

    assert result.is_match is False


def test_returns_non_match_when_no_rules_match():
    result = CandidateMatcher().match(
        _record(full_name="Ada Lovelace", emails=["ada@example.com"]),
        _record(full_name="Grace Hopper", emails=["grace@example.com"]),
    )

    assert result.is_match is False
    assert result.confidence < 0.92
    assert result.reason
