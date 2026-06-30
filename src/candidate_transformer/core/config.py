"""Configuration loading and validation.

This module owns the boundary between untrusted JSON configuration files and
typed application settings. It keeps parsing, validation, logging, and
configuration-specific exceptions in one place so the rest of the application
can depend on a validated ``TransformerConfig`` instance.
"""

from __future__ import annotations

import json
import logging
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from candidate_transformer.core.exceptions import (
    ConfigurationFileNotFoundError,
    ConfigurationParseError,
    ConfigurationReadError,
    ConfigurationValidationError,
)

logger = logging.getLogger(__name__)


class MissingValueStrategy(str, Enum):
    """Supported strategies for handling missing candidate field values."""

    KEEP_NULL = "keep_null"
    OMIT = "omit"
    EMPTY_STRING = "empty_string"


class OutputField(BaseModel):
    """Configuration for one field emitted in the JSON output."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, description="Canonical candidate field name.")
    required: bool = Field(default=False, description="Whether the output field is required.")

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        """Strip whitespace from field names before validation completes."""
        normalized = value.strip()
        if not normalized:
            raise ValueError("field name cannot be blank")
        return normalized


class TransformerConfig(BaseModel):
    """Validated configuration for candidate transformation output behavior."""

    model_config = ConfigDict(extra="forbid")

    output_fields: list[OutputField] = Field(
        ...,
        min_length=1,
        description="Fields to include in generated candidate JSON.",
    )
    field_renaming: dict[str, str] = Field(
        default_factory=dict,
        description="Mapping from canonical field names to output field names.",
    )
    missing_value_strategy: MissingValueStrategy = Field(
        default=MissingValueStrategy.KEEP_NULL,
        description="Strategy used when an output field has no value.",
    )
    source_priorities: dict[str, int] = Field(
        default_factory=dict,
        description="Higher values indicate more trusted candidate data sources.",
    )
    apply_normalization: bool = Field(
        default=False,
        description="Whether output projection should apply final lightweight normalization.",
    )
    use_ai: bool = Field(
        default=False,
        description="Whether to run AI input enrichment before deterministic normalization.",
    )

    @field_validator("field_renaming")
    @classmethod
    def validate_field_renaming(cls, value: dict[str, str]) -> dict[str, str]:
        """Ensure field rename mappings do not contain blank keys or values."""
        normalized: dict[str, str] = {}
        for source_field, output_field in value.items():
            source = source_field.strip()
            target = output_field.strip()
            if not source:
                raise ValueError("field_renaming contains a blank source field")
            if not target:
                raise ValueError(f"field_renaming for '{source}' contains a blank output field")
            normalized[source] = target
        return normalized

    @field_validator("source_priorities")
    @classmethod
    def validate_source_priorities(cls, value: dict[str, int]) -> dict[str, int]:
        """Ensure source priorities are named and non-negative."""
        normalized: dict[str, int] = {}
        for source_name, priority in value.items():
            source = source_name.strip()
            if not source:
                raise ValueError("source_priorities contains a blank source name")
            if priority < 0:
                raise ValueError(f"source priority for '{source}' must be non-negative")
            normalized[source] = priority
        return normalized

    @model_validator(mode="after")
    def validate_renamed_fields_are_output_fields(self) -> TransformerConfig:
        """Ensure every renamed field is present in the configured output fields."""
        output_field_names = {field.name for field in self.output_fields}
        unknown_fields = sorted(set(self.field_renaming) - output_field_names)
        if unknown_fields:
            fields = ", ".join(unknown_fields)
            raise ValueError(f"field_renaming references fields not present in output_fields: {fields}")
        return self


class ConfigurationLoader:
    """Load and validate transformer configuration from JSON files."""

    def load(self, path: str | Path) -> TransformerConfig:
        """Read, parse, and validate a JSON configuration file.

        Args:
            path: Path to a JSON configuration file.

        Returns:
            A validated ``TransformerConfig`` instance.

        Raises:
            ConfigurationFileNotFoundError: If the file does not exist.
            ConfigurationReadError: If the file cannot be read.
            ConfigurationParseError: If the file is not valid JSON.
            ConfigurationValidationError: If the JSON does not match the schema.
        """
        config_path = Path(path)
        logger.info("Loading transformer configuration", extra={"config_path": str(config_path)})

        if not config_path.exists():
            logger.error("Configuration file not found", extra={"config_path": str(config_path)})
            raise ConfigurationFileNotFoundError(f"Configuration file not found: {config_path}")

        try:
            raw_config = config_path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.exception("Failed to read configuration file", extra={"config_path": str(config_path)})
            raise ConfigurationReadError(f"Could not read configuration file '{config_path}': {exc}") from exc

        try:
            payload: Any = json.loads(raw_config)
        except json.JSONDecodeError as exc:
            logger.exception("Configuration file contains invalid JSON", extra={"config_path": str(config_path)})
            raise ConfigurationParseError(
                f"Configuration file '{config_path}' is not valid JSON: {exc.msg}"
            ) from exc

        try:
            config = TransformerConfig.model_validate(payload)
        except ValidationError as exc:
            logger.exception("Configuration validation failed", extra={"config_path": str(config_path)})
            raise ConfigurationValidationError(
                f"Configuration file '{config_path}' failed validation: {exc}"
            ) from exc

        logger.info("Transformer configuration loaded", extra={"config_path": str(config_path)})
        return config
