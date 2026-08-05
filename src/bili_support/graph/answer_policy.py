"""Grounded Answer发布策略：只发布通过结构、引用和NLI门禁的内容。"""

from __future__ import annotations

from bili_support.intent.types import BusinessDomain
from bili_support.knowledge.claim_verification import (
    ClaimSupportStatus,
    GroundedVerificationDecision,
    VerificationMode,
)
from bili_support.llm.service import GroundedChatCompletionResult
from bili_support.routing import CustomerServiceRoutePlan


def publish_grounded_answer(result: GroundedChatCompletionResult) -> str:
    """全量通过发布原文；部分支持时仅从通过的Claim确定性重建。"""

    if result.error_code is not None or result.grounded_answer is None:
        return (
            "知识回答未通过结构或引用校验，本次没有展示未经验证的模型内容。"
            "请换一种描述重试，或转人工核查。"
        )
    verification = result.verification
    if verification is None:
        return "知识校验服务未返回结果，本次已安全拦截。请稍后重试或转人工核查。"
    if verification.mode is VerificationMode.SHADOW and not verification.hard_gate_failed:
        return result.grounded_answer.answer
    if verification.decision is GroundedVerificationDecision.PASS:
        return result.grounded_answer.answer

    supported = tuple(
        claim
        for claim in verification.claims
        if claim.status is ClaimSupportStatus.SUPPORTED
    )
    if supported and not verification.hard_gate_failed:
        statements = []
        for claim in supported:
            text = claim.claim_text.rstrip("。！？； ")
            citations = "".join(f"[{item}]" for item in claim.evidence_ids)
            statements.append(f"{text}{citations}。")
        return "".join(statements) + "其余内容证据不足，建议补充信息或转人工核查。"
    if verification.decision is GroundedVerificationDecision.DEGRADE:
        return "当前证据或语义校验不足，无法形成可靠回答。请缩小问题范围或转人工核查。"
    return "当前生成内容存在缺少证据支持或证据冲突，本次已安全拦截。请补充信息或转人工核查。"


def attach_grounding_trace(
    route_plan: CustomerServiceRoutePlan,
    result: GroundedChatCompletionResult,
) -> CustomerServiceRoutePlan:
    """把实际引用和NLI结论写回公开检索Trace。"""

    retrieval = route_plan.summary.retrieval
    if retrieval is None:
        return route_plan
    used_ids = (
        result.grounded_answer.used_evidence_ids
        if result.grounded_answer is not None
        else ()
    )
    updated_retrieval = retrieval.model_copy(
        update={
            "used_evidence_ids": used_ids,
            "verification": result.verification,
            "grounding_error_code": result.error_code,
        }
    )
    return route_plan.model_copy(
        update={"summary": route_plan.summary.model_copy(update={"retrieval": updated_retrieval})}
    )


def route_domains(route_plan: CustomerServiceRoutePlan) -> tuple[BusinessDomain, ...]:
    """集中暴露路由业务域，便于调试页和后续Agent复用。"""

    return route_plan.summary.business_domains
