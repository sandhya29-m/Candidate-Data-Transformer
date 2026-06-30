"""Unit tests for link classification."""

from candidate_transformer.utils import LinkClassifier


def test_classifies_known_profile_hosts():
    classifier = LinkClassifier()

    assert classifier.classify("https://github.com/octocat").category == "github"
    assert classifier.classify("https://linkedin.com/in/ada").category == "linkedin"
    assert classifier.classify("https://leetcode.com/u/ada").category == "leetcode"
    assert classifier.classify("https://hackerrank.com/ada").category == "hackerrank"


def test_classifies_unknown_professional_site_as_portfolio():
    classification = LinkClassifier().classify("https://ada.dev")

    assert classification.category == "portfolio"
    assert classification.url == "https://ada.dev"


def test_adds_scheme_for_bare_domains():
    classification = LinkClassifier().classify("linkedin.com/in/ada")

    assert classification.category == "linkedin"
    assert classification.url == "https://linkedin.com/in/ada"


def test_returns_none_for_empty_or_invalid_links():
    classifier = LinkClassifier()

    assert classifier.classify(None) is None
    assert classifier.classify("") is None
    assert classifier.classify("not a url") is None
