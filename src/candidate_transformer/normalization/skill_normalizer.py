"""Skill normalization utilities."""

from __future__ import annotations

import re
from collections.abc import Mapping


class SkillNormalizer:
    """Normalize skill aliases into canonical skill names.

    The normalizer uses a configurable alias dictionary. Aliases are matched
    case-insensitively after trimming whitespace and simplifying punctuation,
    while canonical skill names are returned exactly as configured.
    """

    DEFAULT_MAPPINGS: dict[str, str] = {
        "py": "Python",
        "python3": "Python",
        "python 3": "Python",
        "js": "JavaScript",
        "javascript": "JavaScript",
        "node": "Node.js",
        "nodejs": "Node.js",
        "node js": "Node.js",
        "node.js": "Node.js",
    }

    def __init__(self, mappings: Mapping[str, str] | None = None) -> None:
        """Initialize the normalizer.

        Args:
            mappings: Optional alias-to-canonical mapping. Custom mappings are
                merged with defaults and override default aliases.
        """
        merged_mappings = dict(self.DEFAULT_MAPPINGS)
        if mappings is not None:
            merged_mappings.update(mappings)

        self._mappings = {
            self._normalize_lookup_key(alias): canonical.strip()
            for alias, canonical in merged_mappings.items()
            if alias.strip() and canonical.strip()
        }

    def normalize(self, skill: str | None) -> str | None:
        """Return a canonical skill name, cleaned unknown skill, or ``None``.

        Args:
            skill: Raw skill text from a candidate source.

        Returns:
            The configured canonical skill name for known aliases, the trimmed
            original skill for unknown values, or ``None`` for empty input.
        """
        if skill is None:
            return None

        cleaned_skill = self._clean_skill(skill)
        if not cleaned_skill:
            return None

        lookup_key = self._normalize_lookup_key(cleaned_skill)
        return self._mappings.get(lookup_key, cleaned_skill)

    def normalize_many(self, skills: list[str | None]) -> list[str]:
        """Normalize multiple skills and deduplicate them in input order."""
        normalized_skills: list[str] = []
        seen: set[str] = set()

        for skill in skills:
            normalized = self.normalize(skill)
            if normalized is None:
                continue

            key = normalized.casefold()
            if key not in seen:
                normalized_skills.append(normalized)
                seen.add(key)

        return normalized_skills

    def with_mappings(self, mappings: Mapping[str, str]) -> SkillNormalizer:
        """Return a new normalizer with additional or overridden mappings."""
        merged_mappings = {**self._mappings, **{self._normalize_lookup_key(k): v for k, v in mappings.items()}}
        return SkillNormalizer(merged_mappings)

    def _clean_skill(self, skill: str) -> str:
        """Trim and collapse repeated whitespace in a skill value."""
        return " ".join(skill.strip().split())

    def _normalize_lookup_key(self, value: str) -> str:
        """Create a tolerant lookup key for skill alias matching."""
        cleaned_value = self._clean_skill(value).casefold()
        return re.sub(r"[\s._-]+", " ", cleaned_value).strip()
