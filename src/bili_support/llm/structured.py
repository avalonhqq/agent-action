"""Pydantic structured-output parsing with explicit safe degradation."""

from __future__ import annotations

import json
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from bili_support.llm.types import StructuredOutputSpec


class StructuredOutputError(StrEnum):
    """Stable reason codes for structured-output parsing failures."""

    INVALID_JSON = "invalid_json"
    SCHEMA_VALIDATION_FAILED = "schema_validation_failed"


class StructuredOutputResult[T: BaseModel](BaseModel):
    """A parsed value or a safe reason code, never raw model reasoning."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    value: T | None = None
    error_code: StructuredOutputError | None = None

    @model_validator(mode="after")
    def exactly_one_result_must_be_present(self) -> StructuredOutputResult[T]:
        if (self.value is None) == (self.error_code is None):
            raise ValueError("exactly one of value or error_code must be set")
        return self


class StructuredOutputParser[T: BaseModel]:
    """Parse strict JSON into a caller-supplied Pydantic schema."""

    def __init__(self, schema: type[T]) -> None:
        self._schema = schema

    def specification(self, name: str) -> StructuredOutputSpec:
        """Build the provider-neutral JSON Schema request for this parser."""
        return StructuredOutputSpec(
            name=name,
            schema_definition=self._schema.model_json_schema(),
        )

    def parse(self, content: str) -> StructuredOutputResult[T]:
        try:
            payload = json.loads(content)
        except json.JSONDecodeError:
            return StructuredOutputResult[T](error_code=StructuredOutputError.INVALID_JSON)

        try:
            value = self._schema.model_validate(payload)
        except ValidationError:
            return StructuredOutputResult[T](
                error_code=StructuredOutputError.SCHEMA_VALIDATION_FAILED
            )
        return StructuredOutputResult[T](value=value)
