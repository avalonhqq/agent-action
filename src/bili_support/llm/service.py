"""Application service combining prompts, context, providers, and usage."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from time import perf_counter

from pydantic import BaseModel, ConfigDict

from bili_support.core.exceptions import AppError
from bili_support.knowledge.claim_verification import (
    ClaimVerifier,
    GroundedVerificationResult,
    parse_evidence_records,
    verify_grounded_answer,
)
from bili_support.knowledge.grounded_answer import (
    GroundedAnswer,
    GroundedAnswerContractError,
    validate_grounded_answer_evidence,
)
from bili_support.llm.context import (
    BoundedContextBuilder,
    QueryRewriteResult,
    StandaloneQueryRewriter,
)
from bili_support.llm.errors import LLMResponseError
from bili_support.llm.prompts import PromptRegistry
from bili_support.llm.provider import LLMProvider
from bili_support.llm.structured import (
    StructuredOutputError,
    StructuredOutputParser,
    StructuredOutputResult,
)
from bili_support.llm.types import (
    ChatMessage,
    FinishReason,
    LLMRequest,
    LLMResponse,
    StreamChunk,
    TokenUsage,
)
from bili_support.llm.usage import UsageRecord, UsageRecorder, UsageStatus


def _sum_usage(left: TokenUsage, right: TokenUsage) -> TokenUsage:
    """累计结构重试真实消耗，避免会话审计只记录最后一次调用。"""

    prompt_tokens = left.prompt_tokens + right.prompt_tokens
    completion_tokens = left.completion_tokens + right.completion_tokens
    return TokenUsage(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
    )


class ChatCompletionResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    response: LLMResponse
    rewrite: QueryRewriteResult
    prompt_version: str


class GroundedChatCompletionResult(BaseModel):
    """8D知识回答结果：Provider原始元数据与安全解析结果分离。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    response: LLMResponse
    grounded_answer: GroundedAnswer | None = None
    verification: GroundedVerificationResult | None = None
    error_code: str | None = None
    rewrite: QueryRewriteResult
    prompt_version: str


class ChatService:
    """Prepare bounded requests and account for every provider call."""

    def __init__(
        self,
        *,
        provider: LLMProvider,
        model: str,
        prompt_registry: PromptRegistry,
        usage_recorder: UsageRecorder,
        context_builder: BoundedContextBuilder | None = None,
        rewriter: StandaloneQueryRewriter | None = None,
        temperature: float = 0.0,
        max_tokens: int = 512,
        grounded_max_tokens: int | None = None,
        timeout_seconds: float = 30.0,
        grounded_parse_retries: int = 1,
        claim_verifier: ClaimVerifier | None = None,
    ) -> None:
        if not 0 <= grounded_parse_retries <= 2:
            raise ValueError("grounded_parse_retries must be between zero and two")
        if grounded_max_tokens is not None and grounded_max_tokens <= 0:
            raise ValueError("grounded_max_tokens must be greater than zero")
        self._provider = provider
        self._model = model
        self._prompt_registry = prompt_registry
        self._usage_recorder = usage_recorder
        self._context_builder = context_builder or BoundedContextBuilder()
        self._rewriter = rewriter or StandaloneQueryRewriter()
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._grounded_max_tokens = grounded_max_tokens or max_tokens
        self._timeout_seconds = timeout_seconds
        self._grounded_parse_retries = grounded_parse_retries
        # 生产入口注入真实NLI；None仅用于离线兼容工具和不触发语义推理的单元测试。
        self._claim_verifier = claim_verifier

    @property
    def model(self) -> str:
        return self._model

    @property
    def prompt_version(self) -> str:
        return self._prompt_registry.get("support_answer").identifier

    @property
    def grounded_prompt_version(self) -> str:
        """真实知识问答使用的不可变Prompt版本。"""

        return self._prompt_registry.get("grounded_support", version=4).identifier

    async def complete_grounded(
        self,
        *,
        request_id: str,
        user_message: str,
        history: list[ChatMessage],
        evidence_context: str,
        verify_claims: bool = True,
    ) -> GroundedChatCompletionResult:
        """生成严格JSON并校验引用；默认兼容旧链路继续执行NLI。"""

        parser = StructuredOutputParser(GroundedAnswer)
        request, rewrite, prompt_version = self._prepare_grounded(
            user_message,
            history,
            evidence_context=evidence_context,
            structured_output=parser,
        )
        evidence = parse_evidence_records(evidence_context)
        total_usage = TokenUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0)
        for attempt in range(self._grounded_parse_retries + 1):
            operation = "complete:grounded" if attempt == 0 else "complete:grounded_repair"
            started = perf_counter()
            try:
                response = await self._provider.complete(request)
            except asyncio.CancelledError:
                await self._record(
                    request_id,
                    operation,
                    prompt_version,
                    started,
                    UsageStatus.CANCELLED,
                    None,
                    "cancelled",
                )
                raise
            except LLMResponseError as exc:
                await self._record(
                    request_id,
                    operation,
                    prompt_version,
                    started,
                    UsageStatus.ERROR,
                    None,
                    exc.code.value,
                )
                if attempt < self._grounded_parse_retries:
                    request = self._repair_grounded_request(request)
                    continue
                raise
            except AppError as exc:
                await self._record(
                    request_id,
                    operation,
                    prompt_version,
                    started,
                    UsageStatus.ERROR,
                    None,
                    exc.code.value,
                )
                raise
            except Exception:
                await self._record(
                    request_id,
                    operation,
                    prompt_version,
                    started,
                    UsageStatus.ERROR,
                    None,
                    "unexpected_provider_error",
                )
                raise

            total_usage = _sum_usage(total_usage, response.usage)
            # 推理模型可能以length结束并只返回半个JSON，单独标记后走格式修复重试。
            parsed = (
                StructuredOutputResult[GroundedAnswer](
                    error_code=StructuredOutputError.TRUNCATED_RESPONSE
                )
                if response.finish_reason is FinishReason.LENGTH
                else parser.parse(response.content)
            )
            parse_error = parsed.error_code.value if parsed.error_code is not None else None
            if parsed.value is None and attempt < self._grounded_parse_retries:
                await self._record(
                    request_id,
                    operation,
                    prompt_version,
                    started,
                    UsageStatus.ERROR,
                    response.usage,
                    parse_error,
                )
                request = self._repair_grounded_request(request)
                continue

            grounded = parsed.value
            error_code = parse_error
            verification = None
            if grounded is not None:
                try:
                    validate_grounded_answer_evidence(
                        grounded,
                        allowed_evidence_ids=tuple(item.evidence_id for item in evidence),
                    )
                except GroundedAnswerContractError as exc:
                    error_code = exc.code.value
                    grounded = None
                else:
                    if verify_claims:
                        verification = (
                            await self._claim_verifier.verify(grounded, evidence=evidence)
                            if self._claim_verifier is not None
                            else verify_grounded_answer(grounded, evidence=evidence)
                        )

            await self._record(
                request_id,
                operation,
                prompt_version,
                started,
                UsageStatus.SUCCESS if error_code is None else UsageStatus.ERROR,
                response.usage,
                error_code,
            )
            return GroundedChatCompletionResult(
                response=response.model_copy(update={"usage": total_usage}),
                grounded_answer=grounded,
                verification=verification,
                error_code=error_code,
                rewrite=rewrite,
                prompt_version=prompt_version,
            )
        raise AssertionError("grounded parse retry loop must return")

    async def verify_grounded_completion(
        self,
        result: GroundedChatCompletionResult,
        *,
        evidence_context: str,
    ) -> GroundedChatCompletionResult:
        """9B独立NLI节点入口：验证已通过结构与引用白名单的Grounded对象。"""

        if result.error_code is not None or result.grounded_answer is None:
            return result
        evidence = parse_evidence_records(evidence_context)
        verification = (
            await self._claim_verifier.verify(result.grounded_answer, evidence=evidence)
            if self._claim_verifier is not None
            else verify_grounded_answer(result.grounded_answer, evidence=evidence)
        )
        return result.model_copy(update={"verification": verification})

    async def complete(
        self,
        *,
        request_id: str,
        user_message: str,
        history: list[ChatMessage],
        evidence_context: str | None = None,
    ) -> ChatCompletionResult:
        request, rewrite, prompt_version = self._prepare(
            user_message,
            history,
            evidence_context=evidence_context,
        )
        started = perf_counter()
        try:
            response = await self._provider.complete(request)
        except asyncio.CancelledError:
            await self._record(
                request_id,
                "complete",
                prompt_version,
                started,
                UsageStatus.CANCELLED,
                None,
                "cancelled",
            )
            raise
        except AppError as exc:
            await self._record(
                request_id,
                "complete",
                prompt_version,
                started,
                UsageStatus.ERROR,
                None,
                exc.code.value,
            )
            raise
        except Exception:
            await self._record(
                request_id,
                "complete",
                prompt_version,
                started,
                UsageStatus.ERROR,
                None,
                "unexpected_provider_error",
            )
            raise
        await self._record(
            request_id,
            "complete",
            prompt_version,
            started,
            UsageStatus.SUCCESS,
            response.usage,
            None,
        )
        return ChatCompletionResult(
            response=response,
            rewrite=rewrite,
            prompt_version=prompt_version,
        )

    async def stream(
        self,
        *,
        request_id: str,
        user_message: str,
        history: list[ChatMessage],
        evidence_context: str | None = None,
    ) -> AsyncGenerator[StreamChunk, None]:
        request, _, prompt_version = self._prepare(
            user_message,
            history,
            evidence_context=evidence_context,
        )
        started = perf_counter()
        usage = None
        status = UsageStatus.CANCELLED
        error_code: str | None = "stream_closed"
        try:
            async for chunk in self._provider.stream(request):
                usage = chunk.usage or usage
                yield chunk
            status = UsageStatus.SUCCESS
            error_code = None
        except asyncio.CancelledError:
            error_code = "cancelled"
            raise
        except AppError as exc:
            status = UsageStatus.ERROR
            error_code = exc.code.value
            raise
        except Exception:
            status = UsageStatus.ERROR
            error_code = "unexpected_provider_error"
            raise
        finally:
            await self._record(
                request_id, "stream", prompt_version, started, status, usage, error_code
            )

    def _prepare(
        self,
        user_message: str,
        history: list[ChatMessage],
        *,
        evidence_context: str | None = None,
    ) -> tuple[LLMRequest, QueryRewriteResult, str]:
        rewrite = self._rewriter.rewrite(user_message, history)
        prompt_name = "grounded_support" if evidence_context is not None else "support_answer"
        prompt = self._prompt_registry.get(
            prompt_name,
            version=1 if evidence_context is not None else None,
        )
        variables = {"question": rewrite.standalone_query}
        if evidence_context is not None:
            variables["evidence"] = evidence_context
        rendered = prompt.render(variables)
        window = self._context_builder.build(
            system_message=rendered[0],
            history=history,
            current_message=rendered[1],
        )
        request = LLMRequest(
            messages=window.messages,
            model=self._model,
            temperature=self._temperature,
            max_tokens=self._max_tokens,
            timeout_seconds=self._timeout_seconds,
        )
        return request, rewrite, prompt.identifier

    def _prepare_grounded(
        self,
        user_message: str,
        history: list[ChatMessage],
        *,
        evidence_context: str,
        structured_output: StructuredOutputParser[GroundedAnswer],
    ) -> tuple[LLMRequest, QueryRewriteResult, str]:
        """单独构造v2请求，避免普通聊天和旧调用方误收JSON。"""

        rewrite = self._rewriter.rewrite(user_message, history)
        prompt = self._prompt_registry.get("grounded_support", version=4)
        rendered = prompt.render(
            {"question": rewrite.standalone_query, "evidence": evidence_context}
        )
        window = self._context_builder.build(
            system_message=rendered[0],
            history=history,
            current_message=rendered[1],
        )
        return (
            LLMRequest(
                messages=window.messages,
                model=self._model,
                temperature=0.0,
                max_tokens=self._grounded_max_tokens,
                timeout_seconds=self._timeout_seconds,
                structured_output=structured_output.specification("grounded_answer"),
            ),
            rewrite,
            prompt.identifier,
        )

    @staticmethod
    def _repair_grounded_request(request: LLMRequest) -> LLMRequest:
        """不回传失败原文，只基于原问题和证据重新生成一次严格Grounded对象。"""

        messages = list(request.messages)
        system_message = messages[0]
        messages[0] = system_message.model_copy(
            update={
                "content": (
                    system_message.content
                    + "上一次生成未通过JSON结构校验。请根据原问题和原证据重新独立生成；"
                    "必须返回且只返回answer、claims、used_evidence_ids、completeness四个字段。"
                    "claims不能为空，每项必须包含text和evidence_ids；不得增加证据中没有的"
                    "事实或E编号，不得输出Markdown代码块、前缀、后缀或错误解释。"
                )
            }
        )
        return request.model_copy(update={"messages": messages})

    async def _record(
        self,
        request_id: str,
        operation: str,
        prompt_version: str,
        started: float,
        status: UsageStatus,
        usage: TokenUsage | None,
        error_code: str | None,
    ) -> None:
        await self._usage_recorder.record(
            UsageRecord(
                request_id=request_id,
                operation=operation,
                model=self._model,
                prompt_version=prompt_version,
                latency_ms=(perf_counter() - started) * 1000,
                status=status,
                usage=usage,
                error_code=error_code,
            )
        )
