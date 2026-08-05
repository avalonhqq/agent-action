"""意图决策到客服下游的确定性路由。"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from bili_support.conversation_context import ContextResolution
from bili_support.core.exceptions import AppError
from bili_support.intent.hybrid import HybridIntentClassifier
from bili_support.intent.types import (
    BusinessDomain,
    DecisionSource,
    IntentAction,
    IntentDecision,
    IntentRoute,
    RiskLevel,
)
from bili_support.knowledge.evidence import KnowledgeRetrievalTrace
from bili_support.llm.types import FinishReason, TokenUsage


class CustomerServiceTarget(StrEnum):
    """第四周可执行的客服下游；未实现模块必须在名称中明确 Mock。"""

    KNOWLEDGE_RAG = "knowledge_rag"  # 真实知识检索与证据约束回答
    GENERAL_CHAT = "general_chat"  # 闲聊对话，调用 LLM 自由回答
    CLARIFICATION = "clarification"  # 追问澄清，缺少关键信息时触发
    SAFETY = "safety"  # 安全拦截，unsafe 路由命中
    OUT_OF_SCOPE = "out_of_scope"  # 超出服务范围，out_of_domain 路由命中
    HUMAN_SERVICE_MOCK = "human_service_mock"  # 转人工（Mock）
    HUMAN_REVIEW_MOCK = "human_review_mock"  # 人工复核（Mock），高风险或分类失败时兜底


class CustomerServiceRouteSummary(BaseModel):
    """返回给 API、页面和审计日志的稳定路由摘要。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    target: CustomerServiceTarget  # 最终命中的下游目标
    mocked_downstream: bool  # 下游是否为 Mock 实现
    intent_route: IntentRoute | None = None  # 意图分类的顶层路由
    risk: RiskLevel | None = None  # 最终风险等级（可能被策略升级）
    needs_clarification: bool = False  # 是否需要追问澄清
    source: DecisionSource | None = None  # 决策来源：rule / model / hybrid
    rule_id: str | None = None  # 规则命中时携带的规则编号
    applied_policy_ids: tuple[str, ...] = ()  # 后置策略触发的策略编号列表
    classification_error: str | None = None  # 分类失败时的错误码
    business_domains: tuple[BusinessDomain, ...] = ()  # 知识检索使用的业务域
    retrieval: KnowledgeRetrievalTrace | None = None  # 真实RAG检索摘要


class CustomerServiceRoutePlan(BaseModel):
    """内部执行计划：要调用回答模型，还是返回确定性客服消息。

    use_chat_model 和 response_override 互斥：前者 true 走 LLM 回答，
    后者非空走固定回复；两者必须恰好一个生效。
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    summary: CustomerServiceRouteSummary  # 审计路由摘要
    use_chat_model: bool  # 是否调用 LLM 生成回答
    response_override: str | None = None  # 确定性回复文本，非空时跳过 LLM
    # 仅供服务器内部策略选择；exclude防止订单号、账号号等实体进入公开响应。
    intent_decision: IntentDecision | None = Field(default=None, exclude=True)

    @model_validator(mode="after")
    def validate_execution_mode(self) -> CustomerServiceRoutePlan:
        if self.use_chat_model == (self.response_override is not None):
            raise ValueError("route plan must select exactly one response execution mode")
        return self


class CustomerServiceStreamChunk(BaseModel):
    """正式客服流：首个事件携带路由，其余字段兼容原有文本流。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    delta: str = ""  # 增量文本
    finish_reason: FinishReason | None = None  # 流结束原因
    usage: TokenUsage | None = None  # 本请求 Token 用量
    routing: CustomerServiceRouteSummary | None = None  # 首帧携带的路由摘要（仅首个 chunk）
    execution_status: str | None = None  # 9C：completed/interrupted
    execution_id: str | None = None  # MongoDB Checkpoint线程键
    context_resolution: ContextResolution | None = None  # 跨轮主题消解结果


class CustomerServiceRouter:
    """把 hybrid_v3 的语义决策转换为可审计的客服执行目标。"""

    def __init__(self, classifier: HybridIntentClassifier) -> None:
        self._classifier = classifier

    async def route(self, question: str) -> CustomerServiceRoutePlan:
        """将问题逐级路由到客服下游目标。

        决策树（按优先级）：
        1. 分类失败 → HUMAN_REVIEW_MOCK（人工复核兜底）
        2. unsafe 路由 → SAFETY（安全拦截）
        3. out_of_domain 路由 → OUT_OF_SCOPE（超出范围）
        4. chitchat 路由 → GENERAL_CHAT（LLM 闲聊）
        5. 高风险/严重风险 → HUMAN_REVIEW_MOCK（人工复核）
        6. 需要澄清 → CLARIFICATION（追问）
        7. 请求转人工 → HUMAN_SERVICE_MOCK（转人工）
        8. 其他 → KNOWLEDGE_RAG（真实知识检索，正常业务路径）
        """
        try:
            result = await self._classifier.classify(question)
        except AppError as exc:
            return self._classification_fallback(exc.code.value)

        if result.decision is None:
            error_code = result.error_code
            return self._classification_fallback(
                error_code.value if error_code is not None else "unknown"
            )

        decision = result.decision

        # 1. unsafe 路由 → 安全拦截，固定回复后不再调用 LLM。
        if decision.route is IntentRoute.UNSAFE:
            return self._fixed_plan(
                CustomerServiceTarget.SAFETY,
                "抱歉，我不能协助实施可能伤害账号、用户或平台安全的操作。"
                "如果你遇到账号或人身安全问题，我可以提供安全的申诉与求助路径。",
                decision=decision,
                rule_id=result.rule_id,
                applied_policy_ids=result.applied_policy_ids,
            )

        # 2. out_of_domain → 超出服务范围，固定回复。
        if decision.route is IntentRoute.OUT_OF_DOMAIN:
            return self._fixed_plan(
                CustomerServiceTarget.OUT_OF_SCOPE,
                "这个问题超出哔哩哔哩客服的服务范围。"
                "你可以继续咨询账号、会员、订单、创作、内容、社区或客户端问题。",
                decision=decision,
                rule_id=result.rule_id,
                applied_policy_ids=result.applied_policy_ids,
            )

        # 3. chitchat → LLM 自由聊天，不限制回答内容。
        if decision.route is IntentRoute.CHITCHAT:
            return CustomerServiceRoutePlan(
                summary=self._summary(
                    target=CustomerServiceTarget.GENERAL_CHAT,
                    mocked_downstream=False,
                    decision=decision,
                    rule_id=result.rule_id,
                    applied_policy_ids=result.applied_policy_ids,
                ),
                use_chat_model=True,
                intent_decision=decision,
            )

        # 以下均为 supported 路由。

        # 4. 高风险 / 严重风险 → 人工复核，不自动执行操作。
        if decision.risk in {RiskLevel.HIGH, RiskLevel.CRITICAL}:
            return self._fixed_plan(
                CustomerServiceTarget.HUMAN_REVIEW_MOCK,
                "该诉求需要更严格的身份或安全核验，已进入人工复核 Mock 流程。"
                "本阶段不会自动执行高风险操作。",
                decision=decision,
                rule_id=result.rule_id,
                applied_policy_ids=result.applied_policy_ids,
            )

        # 5. 需要澄清 → 追问用户补充信息，不调用 LLM。
        if decision.needs_clarification:
            return self._fixed_plan(
                CustomerServiceTarget.CLARIFICATION,
                decision.clarification_question or "请补充处理该诉求所需的信息。",
                decision=decision,
                rule_id=result.rule_id,
                applied_policy_ids=result.applied_policy_ids,
            )

        # 6. 用户明确要求转人工 → 转人工 Mock。
        if _requests_human_service(decision):
            return self._fixed_plan(
                CustomerServiceTarget.HUMAN_SERVICE_MOCK,
                "已进入人工客服转接 Mock 流程。当前学习环境不会连接真实客服坐席。",
                decision=decision,
                rule_id=result.rule_id,
                applied_policy_ids=result.applied_policy_ids,
            )

        # 7. 正常业务路径 → 真实知识检索 + 证据约束LLM回答。
        return CustomerServiceRoutePlan(
            summary=self._summary(
                target=CustomerServiceTarget.KNOWLEDGE_RAG,
                mocked_downstream=False,
                decision=decision,
                rule_id=result.rule_id,
                applied_policy_ids=result.applied_policy_ids,
            ),
            use_chat_model=True,
            intent_decision=decision,
        )

    @staticmethod
    def _fixed_plan(
        target: CustomerServiceTarget,
        response: str,
        *,
        decision: IntentDecision,
        rule_id: str | None,
        applied_policy_ids: tuple[str, ...],
    ) -> CustomerServiceRoutePlan:
        """构建确定性回复计划：use_chat_model=False 并设置 response_override。

        用于安全拦截、超出范围、澄清追问、人工服务等不需要 LLM 参与的场景。
        """
        return CustomerServiceRoutePlan(
            summary=CustomerServiceRouter._summary(
                target=target,
                # Mock 目标标记为 mocked_downstream，真实目标不标记。
                mocked_downstream=target
                in {
                    CustomerServiceTarget.HUMAN_SERVICE_MOCK,
                    CustomerServiceTarget.HUMAN_REVIEW_MOCK,
                },
                decision=decision,
                rule_id=rule_id,
                applied_policy_ids=applied_policy_ids,
            ),
            use_chat_model=False,
            response_override=response,
            intent_decision=decision,
        )

    @staticmethod
    def _classification_fallback(error_code: str) -> CustomerServiceRoutePlan:
        """分类失败时的兜底：路由到人工复核，不做任何自动操作。"""
        return CustomerServiceRoutePlan(
            summary=CustomerServiceRouteSummary(
                target=CustomerServiceTarget.HUMAN_REVIEW_MOCK,
                mocked_downstream=True,
                classification_error=error_code,
            ),
            use_chat_model=False,
            response_override=(
                "暂时无法可靠识别你的诉求，已进入人工复核 Mock 流程。"
                "本阶段不会在意图不明时自动执行操作。"
            ),
        )

    @staticmethod
    def _summary(
        *,
        target: CustomerServiceTarget,
        mocked_downstream: bool,
        decision: IntentDecision,
        rule_id: str | None,
        applied_policy_ids: tuple[str, ...],
    ) -> CustomerServiceRouteSummary:
        """从意图决策中提取路由摘要，用于审计和日志。"""
        return CustomerServiceRouteSummary(
            target=target,
            mocked_downstream=mocked_downstream,
            intent_route=decision.route,
            risk=decision.risk,
            needs_clarification=decision.needs_clarification,
            source=decision.source,
            rule_id=rule_id,
            applied_policy_ids=applied_policy_ids,
            business_domains=tuple(
                dict.fromkeys(
                    intent.domain
                    for intent in decision.intents
                    if intent.domain is not BusinessDomain.HUMAN_SERVICE
                )
            ),
        )


def _requests_human_service(decision: IntentDecision) -> bool:
    """检查子意图中是否包含明确的人工客服转接请求。"""
    return any(
        intent.domain is BusinessDomain.HUMAN_SERVICE and intent.action is IntentAction.TRANSFER
        for intent in decision.intents
    )
