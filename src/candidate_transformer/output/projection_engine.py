"""Project canonical candidates into configurable JSON output.

The projection engine is the boundary between the internal canonical candidate
model and external JSON consumers. It applies output configuration for field
selection, field renaming, missing-value strategy, and optional final
normalization.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from candidate_transformer.core.config import MissingValueStrategy, TransformerConfig
from candidate_transformer.domain import CanonicalCandidate
from candidate_transformer.normalization import EmailNormalizer, PhoneNormalizer, SkillNormalizer

logger = logging.getLogger(__name__)


class ProjectionError(Exception):
    """Raised when a candidate cannot be projected with the supplied config."""


class ProjectionEngine:
    """Project a ``CanonicalCandidate`` into configurable JSON."""

    def __init__(
        self,
        *,
        email_normalizer: EmailNormalizer | None = None,
        phone_normalizer: PhoneNormalizer | None = None,
        skill_normalizer: SkillNormalizer | None = None,
    ) -> None:
        """Initialize projection dependencies."""
        self._email_normalizer = email_normalizer or EmailNormalizer()
        self._phone_normalizer = phone_normalizer or PhoneNormalizer()
        self._skill_normalizer = skill_normalizer or SkillNormalizer()

    def project(
        self,
        candidate: CanonicalCandidate,
        config: TransformerConfig | dict[str, Any] | str | Path,
    ) -> dict[str, Any]:
        """Return projected JSON for a canonical candidate.

        Args:
            candidate: Canonical candidate model to project.
            config: Validated config, raw config dictionary, or path to config JSON.

        Returns:
            A JSON-serializable dictionary.
        """
        projection_config = self._coerce_config(config)
        logger.info(
            "Projecting candidate",
            extra={"candidate_id": candidate.candidate_id, "field_count": len(projection_config.output_fields)},
        )

        candidate_data = candidate.model_dump(mode="json")
        projected: dict[str, Any] = {}

        for output_field in projection_config.output_fields:
            field_name = output_field.name
            if field_name not in candidate_data:
                raise ProjectionError(f"Configured output field does not exist on CanonicalCandidate: {field_name}")

            value = candidate_data[field_name]
            if projection_config.apply_normalization:
                value = self._normalize_value(field_name, value)

            if self._is_missing(value):
                if projection_config.missing_value_strategy is MissingValueStrategy.OMIT:
                    continue
                value = self._missing_value(projection_config.missing_value_strategy)

            output_name = projection_config.field_renaming.get(field_name, field_name)
            projected[output_name] = self._to_json_value(value)

        logger.info("Projected candidate", extra={"candidate_id": candidate.candidate_id})
        return projected

    def _coerce_config(self, config: TransformerConfig | dict[str, Any] | str | Path) -> TransformerConfig:
        """Coerce supported config inputs into ``TransformerConfig``."""
        if isinstance(config, TransformerConfig):
            return config

        if isinstance(config, dict):
            return TransformerConfig.model_validate(config)

        from candidate_transformer.core.config import ConfigurationLoader

        return ConfigurationLoader().load(config)

    def _normalize_value(self, field_name: str, value: Any) -> Any:
        """Apply optional final normalization for supported projected fields."""
        if field_name == "emails" and isinstance(value, list):
            return self._dedupe([normalized for item in value if (normalized := self._email_normalizer.normalize(item))])

        if field_name == "phones" and isinstance(value, list):
            return self._dedupe([normalized for item in value if (normalized := self._phone_normalizer.normalize(item))])

        if field_name == "skills" and isinstance(value, list):
            skill_names = [item["name"] if isinstance(item, dict) and "name" in item else str(item) for item in value]
            return self._skill_normalizer.normalize_many(skill_names)

        return value

    def _missing_value(self, strategy: MissingValueStrategy) -> Any:
        """Return the configured replacement for a missing value."""
        if strategy is MissingValueStrategy.EMPTY_STRING:
            return ""
        return None

    def _is_missing(self, value: Any) -> bool:
        """Return whether a projected value should be considered missing."""
        return value is None or value == [] or value == {}

    def _to_json_value(self, value: Any) -> Any:
        """Convert Pydantic models and nested values into JSON-serializable data."""
        if isinstance(value, BaseModel):
            return value.model_dump(mode="json")
        if isinstance(value, list):
            return [self._to_json_value(item) for item in value]
        if isinstance(value, dict):
            return {key: self._to_json_value(item) for key, item in value.items()}
        return value

    def _dedupe(self, values: list[str]) -> list[str]:
        """Deduplicate strings while preserving order."""
        deduped: list[str] = []
        seen: set[str] = set()
        for value in values:
            key = value.casefold()
            if key not in seen:
                deduped.append(value)
                seen.add(key)
        return deduped
