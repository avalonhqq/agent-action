"""Versioned prompt templates with explicit, safe rendering rules."""

from __future__ import annotations

from collections.abc import Mapping
from string import Formatter

from pydantic import BaseModel, ConfigDict, Field, field_validator

from bili_support.llm.types import ChatMessage, MessageRole


class PromptError(ValueError):
    """Base class for prompt registry and rendering failures."""


class PromptNotFoundError(PromptError):
    """A requested prompt name or version is not registered."""


class DuplicatePromptError(PromptError):
    """A prompt name/version pair is already registered."""


class PromptRenderError(PromptError):
    """A prompt cannot be rendered from the supplied variables."""


class PromptTemplate(BaseModel):
    """An immutable, versioned pair of system and user templates."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    version: int = Field(gt=0)
    system_template: str
    user_template: str

    @field_validator("system_template", "user_template")
    @classmethod
    def template_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("prompt template must not be blank")
        return value

    @property
    def identifier(self) -> str:
        """Return a stable identifier suitable for logs and evaluations."""
        return f"{self.name}:v{self.version}"

    def render(self, variables: Mapping[str, str]) -> list[ChatMessage]:
        """Render the prompt into provider-neutral chat messages."""
        return [
            ChatMessage(
                role=MessageRole.SYSTEM,
                content=_render_template(self.system_template, variables),
            ),
            ChatMessage(
                role=MessageRole.USER,
                content=_render_template(self.user_template, variables),
            ),
        ]


class PromptRegistry:
    """Store immutable prompt versions and resolve the latest explicitly."""

    def __init__(self) -> None:
        self._prompts: dict[tuple[str, int], PromptTemplate] = {}

    def register(self, prompt: PromptTemplate) -> None:
        key = (prompt.name, prompt.version)
        if key in self._prompts:
            raise DuplicatePromptError(f"prompt already registered: {prompt.identifier}")
        self._prompts[key] = prompt

    def get(self, name: str, version: int | None = None) -> PromptTemplate:
        if version is not None:
            try:
                return self._prompts[(name, version)]
            except KeyError as exc:
                raise PromptNotFoundError(f"prompt not found: {name}:v{version}") from exc

        versions = [item for (prompt_name, _), item in self._prompts.items() if prompt_name == name]
        if not versions:
            raise PromptNotFoundError(f"prompt not found: {name}")
        return max(versions, key=lambda item: item.version)


def create_default_prompt_registry() -> PromptRegistry:
    """Create the prompts used by the Week 2 customer-service flow."""
    registry = PromptRegistry()
    registry.register(
        PromptTemplate(
            name="support_answer",
            version=1,
            system_template=(
                "你是 BiliSupport AI 客服助手。只使用提供的上下文回答；"
                "信息不足时明确说明，不编造政策、订单或用户数据。"
            ),
            user_template="用户问题：{question}",
        )
    )
    return registry


def _render_template(template: str, variables: Mapping[str, str]) -> str:
    formatter = Formatter()
    for _, field_name, format_spec, conversion in formatter.parse(template):
        if field_name is None:
            continue
        if not field_name.isidentifier() or format_spec or conversion:
            raise PromptRenderError("only simple prompt variable names are allowed")
        if field_name not in variables:
            raise PromptRenderError(f"missing prompt variable: {field_name}")

    try:
        rendered = template.format_map(dict(variables))
    except (KeyError, ValueError) as exc:
        raise PromptRenderError("prompt rendering failed") from exc
    if not rendered.strip():
        raise PromptRenderError("rendered prompt must not be blank")
    return rendered
