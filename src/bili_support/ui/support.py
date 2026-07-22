"""Small but usable NiceGUI client for persisted streaming conversations."""

from __future__ import annotations

from fastapi import FastAPI
from nicegui import ui

from bili_support.core.exceptions import AppError
from bili_support.core.security import UserContext, authenticate_user
from bili_support.intent.classifier import IntentClassifier
from bili_support.intent.types import IntentDecision
from bili_support.services.conversations import ConversationService


def register_support_ui(
    fastapi_app: FastAPI,
    *,
    service: ConversationService,
    intent_classifier: IntentClassifier,
    expected_token: str,
    storage_secret: str,
    prefill_demo_credentials: bool = False,
    intent_provider_name: str = "mock",
    intent_model: str = "mock-support-model",
) -> None:
    """Mount the learning UI on an existing FastAPI application."""

    def support_page() -> None:
        state: dict[str, str | None] = {"thread_id": None}
        ui.colors(primary="#00AEEC", secondary="#FB7299")
        with ui.header().classes("items-center"):
            ui.label("BiliSupport AI · 企业客服学习平台").classes("text-h6")
        with ui.row().classes("w-full max-w-6xl mx-auto gap-6 p-4"):
            with ui.card().classes("w-80"):
                ui.label("连接设置").classes("text-h6")
                token = ui.input(
                    "Demo Bearer Token",
                    value=expected_token if prefill_demo_credentials else "",
                    password=True,
                    password_toggle_button=True,
                )
                user_id = ui.input("用户 ID", value="demo-user")
                display_name = ui.input("显示名称", value="演示用户")
                thread = ui.input("Thread ID").props("readonly")
                credential_hint = (
                    "本地 Demo Token 已自动填入；生产环境应接企业 SSO/JWT。"
                    if prefill_demo_credentials
                    else "请输入本地 Demo Token；生产环境应接企业 SSO/JWT。"
                )
                ui.label(credential_hint).classes("text-caption text-grey")
            with ui.column().classes("grow"):
                messages = ui.column().classes(
                    "w-full min-h-96 max-h-[65vh] overflow-auto border rounded p-4"
                )
                question = ui.input("请输入客服问题").classes("w-full")
                with ui.row():
                    create_button = ui.button("新建会话")
                    send_button = ui.button("发送并流式回答")
                    intent_button = ui.button("识别意图", color="secondary")
                with ui.card().classes("w-full"):
                    with ui.row().classes("items-center justify-between w-full"):
                        ui.label("意图识别实验").classes("text-h6")
                        ui.label(
                            f"Provider: {intent_provider_name} · Model: {intent_model}"
                        ).classes("text-caption text-grey")
                    if intent_provider_name == "mock":
                        ui.label(
                            "当前为确定性 Mock，仅验证页面和 Schema 链路，不代表真实分类效果。"
                        ).classes("text-caption text-orange")
                    intent_result = ui.column().classes("w-full gap-2")
                    with intent_result:
                        ui.label("输入问题后点击“识别意图”查看结构化决策。").classes(
                            "text-grey"
                        )

        def actor() -> UserContext:
            return authenticate_user(
                expected_token,
                token.value or "",
                user_id.value or None,
                display_name.value or None,
            )

        async def create_conversation() -> None:
            try:
                conversation = await service.create(actor(), "NiceGUI 客服会话")
            except AppError as exc:
                ui.notify(exc.message, type="negative")
                return
            state["thread_id"] = conversation.thread_id
            thread.value = conversation.thread_id
            messages.clear()
            ui.notify("会话已创建", type="positive")

        async def send() -> None:
            content = (question.value or "").strip()
            if not content:
                ui.notify("请输入问题", type="warning")
                return
            if state["thread_id"] is None:
                await create_conversation()
            if state["thread_id"] is None:
                return
            try:
                current_actor = actor()
            except AppError as exc:
                ui.notify(exc.message, type="negative")
                return
            with messages:
                ui.chat_message(content, name=current_actor.display_name, sent=True)
                with ui.chat_message(name="BiliSupport AI"):
                    answer = ui.markdown("")
            question.value = ""
            complete = ""
            try:
                async for chunk in service.stream(
                    actor=current_actor,
                    thread_id=state["thread_id"],
                    content=content,
                    request_id=f"ui-{conversation_request_id()}",
                ):
                    complete += chunk.delta
                    answer.set_content(complete)
            except AppError as exc:
                answer.set_content(f"请求失败：{exc.message}")

        def render_intent(decision: IntentDecision) -> None:
            intent_result.clear()
            with intent_result:
                with ui.row().classes("items-center gap-2"):
                    ui.badge(f"路由：{decision.route.value}", color="primary")
                    ui.badge(f"风险：{decision.risk.value}", color="secondary")
                    ui.label(f"置信度：{decision.confidence:.2f}")
                ui.label(
                    f"情绪：{decision.sentiment.value} · 来源：{decision.source.value}"
                ).classes("text-caption")
                if decision.intents:
                    ui.label("子意图").classes("text-subtitle2")
                    with ui.row().classes("gap-2"):
                        for item in decision.intents:
                            ui.chip(
                                f"{item.domain.value} + {item.action.value} "
                                f"({item.confidence:.2f})"
                            )
                if decision.entities:
                    ui.label("实体").classes("text-subtitle2")
                    for entity in decision.entities:
                        normalized = (
                            f" → {entity.normalized_value}"
                            if entity.normalized_value is not None
                            else ""
                        )
                        ui.label(
                            f"{entity.type.value}: {entity.raw_value}{normalized}"
                        ).classes("text-body2")
                if decision.needs_clarification:
                    ui.label(
                        f"需要澄清：{decision.clarification_question}"
                    ).classes("text-orange")

        async def classify_intent() -> None:
            content = (question.value or "").strip()
            if not content:
                ui.notify("请输入问题", type="warning")
                return
            try:
                actor()
                result = await intent_classifier.classify(content)
            except AppError as exc:
                ui.notify(exc.message, type="negative")
                return
            except ValueError:
                ui.notify("问题不能为空且不能超过 4000 个字符", type="warning")
                return
            if result.value is None:
                error_code = result.error_code
                message = error_code.value if error_code is not None else "unknown"
                intent_result.clear()
                with intent_result:
                    ui.label(f"模型输出未通过意图校验：{message}").classes(
                        "text-negative"
                    )
                return
            render_intent(result.value)
            ui.notify("意图识别完成", type="positive")

        create_button.on_click(create_conversation)
        send_button.on_click(send)
        intent_button.on_click(classify_intent)
        question.on("keydown.enter", send)

    ui.run_with(
        fastapi_app,
        root=support_page,
        mount_path="/support",
        title="BiliSupport AI",
        language="zh-CN",
        storage_secret=storage_secret,
        show_welcome_message=False,
    )


def conversation_request_id() -> str:
    from uuid import uuid4

    return str(uuid4())
