"""使用 Pydantic 解析结构化输出，并显式、安全地降级。"""

from __future__ import annotations

import json
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from bili_support.llm.types import StructuredOutputSpec


class StructuredOutputError(StrEnum):
    """结构化输出解析失败时对外稳定的原因码。"""

    INVALID_JSON = "invalid_json"
    SCHEMA_VALIDATION_FAILED = "schema_validation_failed"


class StructuredOutputResult[T: BaseModel](BaseModel):
    """只包含解析值或安全错误码，绝不携带模型原始推理。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    value: T | None = None
    error_code: StructuredOutputError | None = None

    @model_validator(mode="after")
    def exactly_one_result_must_be_present(self) -> StructuredOutputResult[T]:
        if (self.value is None) == (self.error_code is None):
            raise ValueError("exactly one of value or error_code must be set")
        return self


class StructuredOutputParser[T: BaseModel]:
    """把严格 JSON 解析为调用方指定的 Pydantic 类型。"""

    def __init__(self, schema: type[T]) -> None:
        self._schema = schema

    def specification(self, name: str) -> StructuredOutputSpec:
        """从同一个 Pydantic 类型生成供应商无关的 JSON Schema 请求。"""
        return StructuredOutputSpec(
            name=name,
            schema_definition=self._schema.model_json_schema(),
        )

    def parse(self, content: str) -> StructuredOutputResult[T]:
        # 第一层只判断语法；合法 JSON 不代表字段和业务组合合法。
        try:
            payload = json.loads(content)
        except json.JSONDecodeError:
            return StructuredOutputResult[T](error_code=StructuredOutputError.INVALID_JSON)

        # 第二层执行字段、枚举、范围和 IntentDecision 跨字段校验。
        try:
            value = self._schema.model_validate(payload)
        except ValidationError:
            return StructuredOutputResult[T](
                error_code=StructuredOutputError.SCHEMA_VALIDATION_FAILED
            )
        return StructuredOutputResult[T](value=value)
