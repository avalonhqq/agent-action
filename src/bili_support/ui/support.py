"""Small but usable NiceGUI client for persisted streaming conversations."""

from __future__ import annotations

from fastapi import FastAPI
from nicegui import ui

from bili_support.core.exceptions import AppError
from bili_support.core.security import UserContext, authenticate_user
from bili_support.services.conversations import ConversationService


def register_support_ui(
    fastapi_app: FastAPI,
    *,
    service: ConversationService,
    expected_token: str,
    storage_secret: str,
    prefill_demo_credentials: bool = False,
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

        create_button.on_click(create_conversation)
        send_button.on_click(send)
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
