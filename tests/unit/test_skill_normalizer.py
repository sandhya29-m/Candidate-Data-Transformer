"""Unit tests for skill normalization."""

from candidate_transformer.normalization import SkillNormalizer


def test_normalize_default_skill_aliases():
    normalizer = SkillNormalizer()

    assert normalizer.normalize("Py") == "Python"
    assert normalizer.normalize("Python3") == "Python"
    assert normalizer.normalize("JS") == "JavaScript"
    assert normalizer.normalize("Node") == "Node.js"


def test_normalize_is_case_and_whitespace_tolerant():
    normalizer = SkillNormalizer()

    assert normalizer.normalize("  pYtHoN3  ") == "Python"
    assert normalizer.normalize("node js") == "Node.js"
    assert normalizer.normalize("node-js") == "Node.js"


def test_unknown_skill_is_trimmed_but_not_guessed():
    assert SkillNormalizer().normalize("  FastAPI  ") == "FastAPI"


def test_empty_skill_returns_none():
    normalizer = SkillNormalizer()

    assert normalizer.normalize(None) is None
    assert normalizer.normalize("") is None
    assert normalizer.normalize("   ") is None


def test_custom_mappings_are_supported():
    normalizer = SkillNormalizer({"ts": "TypeScript", "golang": "Go"})

    assert normalizer.normalize("TS") == "TypeScript"
    assert normalizer.normalize("golang") == "Go"


def test_custom_mappings_override_defaults():
    normalizer = SkillNormalizer({"js": "ECMAScript"})

    assert normalizer.normalize("JS") == "ECMAScript"


def test_normalize_many_deduplicates_in_order():
    normalizer = SkillNormalizer({"ts": "TypeScript"})

    assert normalizer.normalize_many(["Py", "Python3", "TS", None, "FastAPI", "fastapi"]) == [
        "Python",
        "TypeScript",
        "FastAPI",
    ]


def test_with_mappings_returns_extended_normalizer():
    normalizer = SkillNormalizer().with_mappings({"rb": "Ruby"})

    assert normalizer.normalize("rb") == "Ruby"
    assert normalizer.normalize("Py") == "Python"
