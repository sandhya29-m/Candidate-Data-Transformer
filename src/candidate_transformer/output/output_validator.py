"""Validate projected candidate JSON.

The output validator checks the final JSON shape emitted by ``ProjectionEngine``.
It validates against the configured output contract and returns structured
errors instead of raising exceptions to callers.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, create_model

from candidate_transformer.core.config import TransformerConfig

logger = logging.getLogger(__name__)


class OutputValidationError(BaseModel):
    """One validation error found in projected output."""

    model_config = ConfigDict(extra="forbid")

    field: str = Field(..., description="Projected output field related to the error.")
    message: str = Field(..., description="Human-readable validation error.")
    error_type: str = Field(..., description="Stable machine-readable error category.")


class OutputValidationResult(BaseModel):
    """Result returned by ``OutputValidator``."""

    model_config = ConfigDict(extra="forbid")

    is_valid: bool = Field(..., description="Whether projected output passed validation.")
    errors: list[OutputValidationError] = Field(default_factory=list, description="Validation errors.")


class OutputValidator:
    """Validate projected JSON using a Pydantic model generated from config."""

    def validate(
        self,
        projected_json: Any,
        config: TransformerConfig | dict[str, Any] | str | Path,
    ) -> OutputValidationResult:
        """Validate projected JSON and return a non-throwing result."""
        try:
            projection_config = self._coerce_config(config)
            logger.info("Validating projected output", extra={"field_count": len(projection_config.output_fields)})

            if not isinstance(projected_json, dict):
                return self._invalid("root", "Projected output must be a JSON object.", "invalid_root_type")

            errors: list[OutputValidationError] = []
            errors.extend(self._validate_with_pydantic(projected_json, projection_config))
            errors.extend(self._validate_required_values(projected_json, projection_config))
            errors.extend(self._validate_json_serializable(projected_json))

            result = OutputValidationResult(is_valid=not errors, errors=errors)
            logger.info("Validated projected output", extra={"is_valid": result.is_valid, "errors": len(errors)})
            return result
        except Exception as exc:
            logger.exception("Output validation failed unexpectedly")
            return self._invalid("root", f"Unexpected validation failure: {exc}", "validator_error")

    def _coerce_config(self, config: TransformerConfig | dict[str, Any] | str | Path) -> TransformerConfig:
        """Coerce supported config inputs into ``TransformerConfig``."""
        if isinstance(config, TransformerConfig):
            return config
        if isinstance(config, dict):
            return TransformerConfig.model_validate(config)

        from candidate_transformer.core.config import ConfigurationLoader

        return ConfigurationLoader().load(config)

    def _validate_with_pydantic(
        self,
        projected_json: dict[str, Any],
        config: TransformerConfig,
    ) -> list[OutputValidationError]:
        """Validate projected keys with a generated Pydantic model."""
        model_fields: dict[str, tuple[type[Any], Any]] = {}
        for output_field in config.output_fields:
            output_name = config.field_renaming.get(output_field.name, output_field.name)
            default = ... if output_field.required else None
            model_fields[output_name] = (Any, default)

        output_model = create_model(
            "ProjectedOutputModel",
            __config__=ConfigDict(extra="forbid"),
            **model_fields,
        )

        try:
            output_model.model_validate(projected_json)
            return []
        except ValidationError as exc:
            return [
                OutputValidationError(
                    field=self._location_to_field(error.get("loc", ())),
                    message=str(error.get("msg", "Invalid value.")),
                    error_type=str(error.get("type", "validation_error")),
                )
                for error in exc.errors()
            ]

    def _validate_required_values(
        self,
        projected_json: dict[str, Any],
        config: TransformerConfig,
    ) -> list[OutputValidationError]:
        """Validate that required fields are present and not missing-like."""
        errors: list[OutputValidationError] = []
        for output_field in config.output_fields:
            if not output_field.required:
                continue
            output_name = config.field_renaming.get(output_field.name, output_field.name)
            value = projected_json.get(output_name)
            if value in (None, "", [], {}):
                errors.append(
                    OutputValidationError(
                        field=output_name,
                        message="Required field is missing or empty.",
                        error_type="required_missing",
                    )
                )
        return errors

    def _validate_json_serializable(self, projected_json: dict[str, Any]) -> list[OutputValidationError]:
        """Validate that projected output can be serialized as JSON."""
        try:
            json.dumps(projected_json)
            return []
        except (TypeError, ValueError) as exc:
            return [
                OutputValidationError(
                    field="root",
                    message=f"Projected output is not JSON serializable: {exc}",
                    error_type="not_json_serializable",
                )
            ]

    def _location_to_field(self, location: tuple[Any, ...]) -> str:
        """Convert a Pydantic error location into a display field name."""
        if not location:
            return "root"
        return ".".join(str(part) for part in location)

    def _invalid(self, field: str, message: str, error_type: str) -> OutputValidationResult:
        """Build an invalid result with one error."""
        return OutputValidationResult(
            is_valid=False,
            errors=[OutputValidationError(field=field, message=message, error_type=error_type)],
        )
