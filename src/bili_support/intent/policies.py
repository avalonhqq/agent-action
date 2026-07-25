"""模型意图结果的确定性业务兜底策略。"""

from __future__ import annotations

import re
from collections.abc import Iterable

from pydantic import BaseModel, ConfigDict

from bili_support.intent.types import (
    BusinessDomain,
    DecisionSource,
    EntityType,
    IntentAction,
    IntentDecision,
    IntentRoute,
    RiskLevel,
)

# 将风险等级映射为可比较的数值，用于取"更严重"的一方。
_RISK_ORDER = {
    RiskLevel.LOW: 0,
    RiskLevel.MEDIUM: 1,
    RiskLevel.HIGH: 2,
    RiskLevel.CRITICAL: 3,
}

# 这里只定义“最低风险”，策略只能向上升级，不能把模型识别出的风险静默降级。
_INTENT_RISK_FLOORS = {
    (BusinessDomain.MEMBERSHIP, IntentAction.REFUND): RiskLevel.MEDIUM,
    (BusinessDomain.ORDER, IntentAction.REFUND): RiskLevel.MEDIUM,
    (BusinessDomain.ACCOUNT, IntentAction.RECOVER): RiskLevel.HIGH,
    (BusinessDomain.ACCOUNT, IntentAction.APPEAL): RiskLevel.MEDIUM,
    (BusinessDomain.CREATOR, IntentAction.APPEAL): RiskLevel.MEDIUM,
    (BusinessDomain.CONTENT, IntentAction.APPEAL): RiskLevel.MEDIUM,
    (BusinessDomain.CONTENT, IntentAction.REPORT): RiskLevel.MEDIUM,
    (BusinessDomain.COMMUNITY, IntentAction.APPEAL): RiskLevel.MEDIUM,
    (BusinessDomain.COMMUNITY, IntentAction.REPORT): RiskLevel.MEDIUM,
}

# 当用户问题中包含这些词时，判定为"询问流程"而非"要求立即执行"，
# 此时不因缺少参数而触发澄清追问——下游模块再收集参数。
_PROCESS_MARKERS = (
    "怎么",
    "如何",
    "在哪里",
    "哪儿",
    "入口",
    "流程",
    "教程",
    "步骤",
    "需要什么",
    "告诉我怎么",
)
# 当用户问题中包含这些词时，判定为"要求立即执行"，
# 此时若缺少关键标识（订单号、内容 ID 等），需要触发澄清追问。
_EXECUTION_MARKERS = (
    "帮我",
    "替我",
    "给我",
    "请",
    "我要",
    "我想",
    "查一下",
    "申请",
    "提交",
    "退款",
    "取消",
    "举报",
    "修改",
    "换成",
)
# 匹配订单号格式：可选 BILI 前缀 + 至少 8 位大写字母/数字/连字符。
_ORDER_ID_PATTERN = re.compile(r"\b(?:BILI)?[A-Z0-9-]{8,}\b", re.IGNORECASE)
# 匹配 B 站内容 ID 格式：BV 或 AV 开头 + 至少 5 个字符。
_CONTENT_ID_PATTERN = re.compile(r"\b(?:BV|AV)\w{5,}\b", re.IGNORECASE)
# 匹配凭证窃取类请求，命中后风险升级为 critical。
_CREDENTIAL_THEFT_PATTERN = re.compile(
    r"(?:偷取|窃取|盗取|获取).{0,12}(?:登录凭证|密码|cookie|token|令牌)",
    re.IGNORECASE,
)
# 匹配隐蔽自残/自伤类请求，命中后风险升级为 critical。
_COVERT_SELF_HARM_PATTERN = re.compile(
    r"(?:自残|自伤).{0,16}(?:不被发现|不会被?发现|不容易被?发现|隐蔽|偷偷)"
    r"|(?:不被发现|不会被?发现|不容易被?发现|隐蔽|偷偷).{0,16}(?:自残|自伤)"
)


class IntentPolicyResult(BaseModel):
    """后置策略结果；策略编号用于日志、评估和问题追踪。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    decision: IntentDecision
    applied_policy_ids: tuple[str, ...] = ()


class HybridIntentPolicy:
    """对模型结果执行保守、可解释且确定性的业务校正。"""

    def apply(
            self,
            *,
            question: str,
            decision: IntentDecision,
    ) -> IntentPolicyResult:
        """对模型决策执行两阶段确定性兜底：风险地板 + 缺失参数澄清。

        策略只做保守修正（升级风险、补充澄清），不静默降级模型结果。
        """
        if decision.source is not DecisionSource.MODEL:
            raise ValueError("hybrid policy only accepts model decisions")

        policy_ids: list[str] = []

        # ── 第一阶段：风险地板 ──
        # 根据业务域/动作组合和用户原文中的危险模式，强制提升风险至最低可接受等级。
        risk_floor, risk_policy_id = self._risk_floor(question, decision)
        risk = decision.risk
        if _RISK_ORDER[risk] < _RISK_ORDER[risk_floor]:
            risk = risk_floor
            if risk_policy_id is not None:
                policy_ids.append(risk_policy_id)

        # ── 第二阶段：缺失参数澄清 ──
        # 当模型未识别出澄清需求，但用户要求立即执行却缺少关键标识时，补充澄清追问。
        clarification_question, clarification_policy_id = (
            self._missing_parameter_clarification(question, decision)
        )
        needs_clarification = decision.needs_clarification
        final_clarification_question = decision.clarification_question
        if not needs_clarification and clarification_question is not None:
            needs_clarification = True
            final_clarification_question = clarification_question
            if clarification_policy_id is not None:
                policy_ids.append(clarification_policy_id)

        # 没有策略被触发，原样返回模型决策。
        if not policy_ids:
            return IntentPolicyResult(decision=decision)

        # 至少一个策略触发，重建决策对象并将 source 标记为 hybrid。
        corrected = IntentDecision.model_validate(
            {
                **decision.model_dump(),
                "risk": risk,
                "needs_clarification": needs_clarification,
                "clarification_question": final_clarification_question,
                "source": DecisionSource.HYBRID,
            }
        )
        return IntentPolicyResult(
            decision=corrected,
            applied_policy_ids=tuple(policy_ids),
        )

    @staticmethod
    def _risk_floor(
            question: str,
            decision: IntentDecision,
    ) -> tuple[RiskLevel, str | None]:
        """计算当前决策的风险最低可接受等级。

        两条路径：
        1. unsafe 路由：用正则捕捉凭证窃取/隐蔽自残，否则至少 medium。
        2. supported 路由：遍历子意图，取 _INTENT_RISK_FLOORS 中的最高风险地板。
        """
        # unsafe 路由的特殊正则检测。
        if decision.route is IntentRoute.UNSAFE:
            if _CREDENTIAL_THEFT_PATTERN.search(question):
                return RiskLevel.CRITICAL, "risk.credential_theft:v1"
            if _COVERT_SELF_HARM_PATTERN.search(question):
                return RiskLevel.CRITICAL, "risk.covert_self_harm:v1"
            return RiskLevel.MEDIUM, "risk.unsafe_minimum:v1"

        # supported 路由：遍历子意图取最高风险地板。
        floor = RiskLevel.LOW
        policy_id: str | None = None
        for intent in decision.intents:
            candidate = _INTENT_RISK_FLOORS.get(
                (intent.domain, intent.action),
                RiskLevel.LOW,
            )
            if _RISK_ORDER[candidate] > _RISK_ORDER[floor]:
                floor = candidate
                policy_id = (
                    f"risk.{intent.domain.value}.{intent.action.value}:v1"
                )
        return floor, policy_id

    def _missing_parameter_clarification(
            self,
            question: str,
            decision: IntentDecision,
    ) -> tuple[str | None, str | None]:
        """检测"要求立即执行但缺少关键参数"的场景，返回澄清追问文本。

        三层前置守卫：
        1. 非 supported 路由不检查。
        2. 询问流程类问题不触发（下游模块再收集参数）。
        3. 不包含执行标记词不触发。

        命中后按 (domain, action) 匹配具体规则，每条规则检查对应标识是否存在。
        """
        # 守卫 1：非 supported 路由不检查。
        if decision.route is not IntentRoute.SUPPORTED:
            return None, None
        # 守卫 2：询问流程的问题不触发澄清。
        if self._is_process_question(question):
            return None, None
        # 守卫 3：不包含执行标记词不触发。
        if not any(marker in question for marker in _EXECUTION_MARKERS):
            return None, None

        for intent in decision.intents:
            key = (intent.domain, intent.action)
            # 订单查询/取消/退款 → 缺少订单号。
            if key in {
                (BusinessDomain.ORDER, IntentAction.QUERY),
                (BusinessDomain.ORDER, IntentAction.CANCEL),
                (BusinessDomain.ORDER, IntentAction.REFUND),
            } and not self._has_order_id(question, decision):
                return (
                    "请提供需要处理的订单号。",
                    f"clarification.{intent.domain.value}.{intent.action.value}:v1",
                )
            # 大会员退款 → 缺少交易号或订单号。
            if (
                    key == (BusinessDomain.MEMBERSHIP, IntentAction.REFUND)
                    and not self._has_any_entity(
                decision,
                {EntityType.ORDER_ID, EntityType.TRANSACTION_ID},
            )
            ):
                return (
                    "请提供自动扣费的交易号或订单号。",
                    "clarification.membership.refund:v1",
                )
            # 内容举报 → 缺少内容 ID。
            if key == (
                    BusinessDomain.CONTENT,
                    IntentAction.REPORT,
            ) and not self._has_content_id(question, decision):
                return (
                    "请提供需要举报的内容链接或内容 ID，并说明举报原因。",
                    "clarification.content.report:v1",
                )
            # 账号资料修改 → 缺少账号 ID 或修改说明。
            if key == (
                    BusinessDomain.ACCOUNT,
                    IntentAction.MODIFY,
            ) and not self._has_any_entity(
                decision,
                {EntityType.ACCOUNT_ID, EntityType.OTHER},
            ):
                return (
                    "请说明需要修改的账号资料及新的信息。",
                    "clarification.account.modify:v1",
                )
        return None, None

    @staticmethod
    def _is_process_question(question: str) -> bool:
        return any(marker in question for marker in _PROCESS_MARKERS)

    @staticmethod
    def _has_any_entity(
            decision: IntentDecision,
            entity_types: Iterable[EntityType],
    ) -> bool:
        required = frozenset(entity_types)
        return any(entity.type in required for entity in decision.entities)

    def _has_order_id(
            self,
            question: str,
            decision: IntentDecision,
    ) -> bool:
        return self._has_any_entity(
            decision,
            {EntityType.ORDER_ID},
        ) or _ORDER_ID_PATTERN.search(question) is not None

    def _has_content_id(
            self,
            question: str,
            decision: IntentDecision,
    ) -> bool:
        return self._has_any_entity(
            decision,
            {EntityType.CONTENT_ID},
        ) or _CONTENT_ID_PATTERN.search(question) is not None
