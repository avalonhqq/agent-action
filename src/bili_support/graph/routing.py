"""第9周9A：只根据结构化State选择下一节点的确定性条件边。"""

from __future__ import annotations

from typing import Literal

from bili_support.graph.state import CustomerServiceGraphState, GraphInputStatus


def route_after_input_validation(
    state: CustomerServiceGraphState,
) -> Literal["complete", "fail"]:
    """合法输入进入下一阶段入口；其他状态一律失败关闭。"""

    if state["input_status"] is GraphInputStatus.VALID:
        return "complete"
    return "fail"
