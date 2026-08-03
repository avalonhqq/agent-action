"""BiliSupport统一业务工作台：问答、知识入库、词典审核与发布。"""

from __future__ import annotations

from uuid import uuid4

from fastapi import FastAPI
from nicegui import events, ui
from nicegui.elements.tabs import Tab, Tabs

from bili_support.core.exceptions import AppError
from bili_support.core.security import UserContext, authenticate_user
from bili_support.intent.hybrid import HybridIntentClassifier
from bili_support.intent.types import BusinessDomain, IntentDecision
from bili_support.knowledge.chunking import DocumentKnowledgeType
from bili_support.knowledge.dictionary import (
    DictionarySourceType,
    DictionaryTermStatus,
    DictionaryTermType,
)
from bili_support.routing import CustomerServiceRouteSummary
from bili_support.schemas.dictionary import DictionaryTermCreate
from bili_support.services.conversations import ConversationService
from bili_support.services.dictionary import KnowledgeDictionaryService
from bili_support.services.knowledge import KnowledgeIngestionService

_DOMAIN_OPTIONS = {
    domain.value: {
        "membership": "大会员",
        "order": "订单",
        "account": "账号",
        "creator": "创作者",
        "content": "内容",
        "community": "社区",
        "technical": "技术支持",
        "human_service": "人工服务",
    }[domain.value]
    for domain in BusinessDomain
}
_KNOWLEDGE_TYPE_OPTIONS = {
    item.value: {
        "policy": "政策规则",
        "manual": "操作手册",
        "faq": "FAQ问答",
        "generic": "通用文档",
        "mixed": "综合文档",
    }[item.value]
    for item in DocumentKnowledgeType
}
_TERM_TYPE_OPTIONS = {
    DictionaryTermType.PRODUCT.value: "产品",
    DictionaryTermType.FEATURE.value: "功能",
    DictionaryTermType.ISSUE.value: "问题现象",
    DictionaryTermType.ACTION.value: "操作动作",
    DictionaryTermType.ERROR_CODE.value: "错误码",
    DictionaryTermType.OTHER.value: "其他",
}
_SOURCE_OPTIONS = {
    DictionarySourceType.MANUAL.value: "人工提交",
    DictionarySourceType.KNOWLEDGE_KEYWORD.value: "知识关键词",
    DictionarySourceType.PRODUCT_CATALOG.value: "产品目录",
    DictionarySourceType.CONVERSATION_LOG_MOCK.value: "会话日志 Mock",
    DictionarySourceType.TICKET_MOCK.value: "客服工单 Mock",
}


def register_support_ui(
    fastapi_app: FastAPI,
    *,
    service: ConversationService,
    intent_classifier: HybridIntentClassifier,
    knowledge_service: KnowledgeIngestionService,
    dictionary_service: KnowledgeDictionaryService,
    expected_token: str,
    storage_secret: str,
    prefill_demo_credentials: bool = False,
    intent_provider_name: str = "mock",
    intent_model: str = "mock-support-model",
) -> None:
    """把统一工作台挂载到FastAPI；页面只调用已装配Service。"""

    def support_page() -> None:
        ui.colors(primary="#00A1D6", secondary="#FB7299", accent="#23ADE5")
        ui.add_css(
            """
            body { background: #f6f7fb; color: #1f2937; }
            .workbench-card { border: 1px solid #e5e7eb; border-radius: 16px;
                box-shadow: 0 6px 24px rgba(31, 41, 55, .06); }
            .feature-card { min-height: 180px; transition: transform .18s ease,
                box-shadow .18s ease; }
            .feature-card:hover { transform: translateY(-3px);
                box-shadow: 0 12px 28px rgba(0, 161, 214, .14); }
            .section-title { font-weight: 700; color: #111827; }
            """
        )
        state: dict[str, str | None] = {"thread_id": None}

        with ui.header().classes(
            "items-center justify-between px-6 bg-white text-slate-800 border-b"
        ):
            with ui.row().classes("items-center gap-3"):
                ui.avatar("B", color="primary", text_color="white")
                with ui.column().classes("gap-0"):
                    ui.label("BiliSupport AI").classes("text-h6 font-bold")
                    ui.label("哔哩哔哩企业智能客服工作台").classes("text-caption text-grey-7")
            with ui.row().classes("items-center gap-2"):
                ui.badge("知识链路真实", color="positive")
                ui.badge(
                    "意图 Mock" if intent_provider_name == "mock" else "意图模型已接入",
                    color="orange" if intent_provider_name == "mock" else "positive",
                )

        with ui.tabs().classes("w-full bg-white border-b") as tabs:
            overview_tab = ui.tab("工作台", icon="dashboard")
            chat_tab = ui.tab("智能问答", icon="forum")
            knowledge_tab = ui.tab("知识入库", icon="upload_file")
            terms_tab = ui.tab("领域词条", icon="library_books")
            review_tab = ui.tab("审核发布", icon="fact_check")
            status_tab = ui.tab("能力说明", icon="account_tree")

        with ui.column().classes("w-full max-w-7xl mx-auto px-5 py-4 gap-4"):
            with ui.expansion("连接身份", icon="vpn_key", value=False).classes(
                "w-full bg-white workbench-card"
            ):
                with ui.row().classes("w-full items-end gap-4 p-2"):
                    token = ui.input(
                        "Bearer Token",
                        value=expected_token if prefill_demo_credentials else "",
                        password=True,
                        password_toggle_button=True,
                    ).classes("w-72")
                    user_id = ui.input("用户 ID", value="demo-user").classes("w-52")
                    display_name = ui.input("显示名称", value="演示用户").classes("w-52")
                    thread = ui.input("当前 Thread ID").props("readonly").classes("grow")
                ui.label("本地使用统一Demo Token；生产环境需要企业SSO/JWT和运营RBAC。").classes(
                    "text-caption text-grey-7 px-2 pb-2"
                )

            with ui.tab_panels(tabs, value=overview_tab).classes("w-full bg-transparent"):
                with ui.tab_panel(overview_tab):
                    _render_overview(
                        tabs=tabs,
                        destinations=(
                            (
                                "智能客服问答",
                                "意图识别、Hybrid RAG、引用、拒答与流式响应",
                                "support_agent",
                                "真实知识链路",
                                chat_tab,
                            ),
                            (
                                "企业知识入库",
                                "上传PDF、Word、Markdown和TXT，自动解析与分块",
                                "cloud_upload",
                                "真实数据库",
                                knowledge_tab,
                            ),
                            (
                                "领域词条管理",
                                "新增产品词、别名、来源和Jieba词频",
                                "menu_book",
                                "写入MySQL",
                                terms_tab,
                            ),
                            (
                                "词条审核发布",
                                "候选审核、不可变版本、制品下载与回滚",
                                "verified",
                                "真实状态机",
                                review_tab,
                            ),
                            (
                                "能力与边界",
                                "查看当前真实模块、Mock模块和后续商业化边界",
                                "schema",
                                "可审计",
                                status_tab,
                            ),
                        ),
                    )

                with ui.tab_panel(chat_tab):
                    with ui.row().classes("w-full items-center justify-between"):
                        _section_heading(
                            "智能客服问答",
                            "从意图识别到Hybrid检索、策略门禁和证据约束回答。",
                        )
                        ui.label(
                            f"Provider: {intent_provider_name} · Model: {intent_model}"
                        ).classes("text-caption text-grey-7")
                    messages = ui.column().classes(
                        "w-full min-h-[360px] max-h-[58vh] overflow-auto "
                        "bg-white workbench-card p-5"
                    )
                    with messages:
                        ui.label("新建会话后开始提问。").classes("text-grey-6")
                    question = ui.input(
                        "请输入客服问题",
                        placeholder="例如：大会员支付成功后多久生效？",
                    ).classes("w-full")
                    with ui.row().classes("gap-3"):
                        create_button = ui.button("新建会话", icon="add_comment")
                        send_button = ui.button("发送并流式回答", icon="send")
                        intent_button = ui.button(
                            "仅识别意图", icon="psychology", color="secondary"
                        )
                    with ui.card().classes("w-full workbench-card"):
                        ui.label("意图识别结果").classes("text-subtitle1 font-bold")
                        intent_result = ui.column().classes("w-full gap-2")
                        with intent_result:
                            ui.label("输入问题后点击“仅识别意图”。").classes("text-grey-6")

                with ui.tab_panel(knowledge_tab):
                    _section_heading(
                        "企业知识入库",
                        "文件会进入Loader、SourceBlock、Chunk和版本化存储。",
                    )
                    with ui.row().classes("w-full items-start gap-5"):
                        with ui.card().classes("w-full lg:w-[420px] workbench-card"):
                            knowledge_title = ui.input(
                                "知识标题", placeholder="例如：大会员开通说明"
                            ).classes("w-full")
                            knowledge_domain = ui.select(
                                _DOMAIN_OPTIONS,
                                value=BusinessDomain.MEMBERSHIP.value,
                                label="业务域",
                            ).classes("w-full")
                            knowledge_type = ui.select(
                                _KNOWLEDGE_TYPE_OPTIONS,
                                value=DocumentKnowledgeType.MIXED.value,
                                label="知识类型",
                            ).classes("w-full")
                            access_scope = ui.input("权限标签", value="public").classes("w-full")
                            uploader = (
                                ui.upload(
                                    label="选择 PDF / DOCX / Markdown / TXT",
                                    auto_upload=True,
                                    max_file_size=knowledge_service.max_file_bytes,
                                )
                                .props("accept=.pdf,.docx,.md,.markdown,.txt")
                                .classes("w-full")
                            )
                            upload_result = ui.column().classes("w-full")
                        with ui.card().classes("grow workbench-card"):
                            with ui.row().classes("w-full justify-between items-center"):
                                ui.label("已入库知识").classes("text-h6 section-title")
                                refresh_documents_button = ui.button("刷新", icon="refresh").props(
                                    "flat"
                                )
                            document_table = ui.table(
                                columns=[
                                    {"name": "title", "label": "标题", "field": "title"},
                                    {"name": "domain", "label": "业务域", "field": "domain"},
                                    {"name": "type", "label": "类型", "field": "type"},
                                    {"name": "scope", "label": "权限", "field": "scope"},
                                    {"name": "status", "label": "状态", "field": "status"},
                                ],
                                rows=[],
                                row_key="id",
                                pagination=8,
                            ).classes("w-full")

                with ui.tab_panel(terms_tab):
                    _section_heading(
                        "领域词条管理",
                        "新增词条只进入candidate，必须在审核页面批准后才能发布。",
                    )
                    with ui.row().classes("w-full items-start gap-5"):
                        with ui.card().classes("w-full lg:w-[420px] workbench-card"):
                            term_input = ui.input("领域词", placeholder="例如：超级大会员").classes(
                                "w-full"
                            )
                            aliases_input = ui.input(
                                "别名（逗号分隔）", placeholder="例如：超会, SVIP"
                            ).classes("w-full")
                            term_domain = ui.select(
                                _DOMAIN_OPTIONS,
                                value=BusinessDomain.MEMBERSHIP.value,
                                label="业务域",
                            ).classes("w-full")
                            term_type = ui.select(
                                _TERM_TYPE_OPTIONS,
                                value=DictionaryTermType.PRODUCT.value,
                                label="词条类型",
                            ).classes("w-full")
                            term_frequency = ui.number(
                                "Jieba词频", value=6000, min=1, max=100_000_000
                            ).classes("w-full")
                            term_source = ui.select(
                                _SOURCE_OPTIONS,
                                value=DictionarySourceType.MANUAL.value,
                                label="候选来源",
                            ).classes("w-full")
                            source_reference = ui.input(
                                "来源标识", placeholder="例如：catalog-2026-08"
                            ).classes("w-full")
                            create_term_button = ui.button(
                                "写入候选词", icon="save", color="primary"
                            ).classes("w-full")
                            term_form_result = ui.label("").classes("text-caption")
                        with ui.card().classes("grow workbench-card"):
                            with ui.row().classes("w-full justify-between items-center"):
                                ui.label("数据库词条").classes("text-h6 section-title")
                                refresh_terms_button = ui.button("刷新", icon="refresh").props(
                                    "flat"
                                )
                            term_table = ui.table(
                                columns=[
                                    {"name": "term", "label": "词条", "field": "term"},
                                    {"name": "aliases", "label": "别名", "field": "aliases"},
                                    {"name": "domain", "label": "业务域", "field": "domain"},
                                    {"name": "source", "label": "来源", "field": "source"},
                                    {"name": "status", "label": "状态", "field": "status"},
                                ],
                                rows=[],
                                row_key="id",
                                pagination=10,
                            ).classes("w-full")

                with ui.tab_panel(review_tab):
                    _section_heading(
                        "审核与版本发布",
                        "审核人与发布动作会写入MySQL；Mock候选不能绕过审核。",
                    )
                    with ui.row().classes("w-full items-end gap-4"):
                        review_note = ui.input("审核意见", value="业务资料已确认").classes("grow")
                        refresh_review_button = ui.button("刷新候选", icon="refresh")
                    review_list = ui.column().classes("w-full gap-3")
                    with review_list:
                        ui.label("点击“刷新候选”加载待审核词条。")
                    ui.separator()
                    with ui.row().classes("w-full items-end gap-4"):
                        release_note = ui.input(
                            "发布说明", placeholder="例如：新增会员产品词"
                        ).classes("grow")
                        publish_button = ui.button("发布新版本", icon="publish", color="positive")
                        refresh_versions_button = ui.button("刷新版本", icon="refresh").props(
                            "flat"
                        )
                    with ui.row().classes("w-full items-start gap-5"):
                        version_table = ui.table(
                            columns=[
                                {"name": "version", "label": "版本", "field": "version"},
                                {"name": "status", "label": "状态", "field": "status"},
                                {"name": "count", "label": "词数", "field": "count"},
                                {"name": "hash", "label": "SHA-256", "field": "hash"},
                                {"name": "note", "label": "说明", "field": "note"},
                            ],
                            rows=[],
                            row_key="id",
                            pagination=8,
                        ).classes("grow workbench-card")
                        with ui.card().classes("w-full lg:w-[390px] workbench-card"):
                            with ui.row().classes("w-full justify-between items-center"):
                                ui.label("当前发布制品").classes("text-subtitle1 font-bold")
                                artifact_button = ui.button("查看", icon="description").props(
                                    "flat"
                                )
                            artifact_meta = ui.label("尚未加载").classes("text-caption text-grey-7")
                            artifact_preview = (
                                ui.textarea("Jieba词典预览")
                                .props("readonly autogrow")
                                .classes("w-full")
                            )

                with ui.tab_panel(status_tab):
                    _render_capabilities(intent_provider_name=intent_provider_name)

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
                    route_label = ui.label("").classes("text-caption text-grey-7")
                    route_detail = ui.markdown("").classes("text-caption text-grey-7")
                    answer = ui.markdown("")
            question.value = ""
            complete = ""
            try:
                async for chunk in service.stream(
                    actor=current_actor,
                    thread_id=state["thread_id"],
                    content=content,
                    request_id=f"ui-{uuid4()}",
                ):
                    if chunk.routing is not None:
                        mock_label = " · Mock下游" if chunk.routing.mocked_downstream else ""
                        route_label.set_text(f"路由：{chunk.routing.target.value}{mock_label}")
                        route_detail.set_content(_routing_details(chunk.routing))
                    complete += chunk.delta
                    answer.set_content(complete)
            except AppError as exc:
                answer.set_content(f"请求失败：{exc.message}")

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
                ui.notify("问题不能为空且不能超过4000个字符", type="warning")
                return
            intent_result.clear()
            with intent_result:
                if result.decision is None:
                    code = result.error_code.value if result.error_code else "unknown"
                    ui.label(f"模型输出未通过校验：{code}").classes("text-negative")
                else:
                    _render_intent(
                        result.decision,
                        rule_id=result.rule_id,
                        applied_policy_ids=result.applied_policy_ids,
                    )

        async def upload_knowledge(event: events.UploadEventArguments) -> None:
            title = (knowledge_title.value or "").strip()
            if not title:
                ui.notify("请先填写知识标题", type="warning")
                return
            try:
                result = await knowledge_service.upload(
                    actor=actor(),
                    content=await event.file.read(),
                    filename=event.file.name,
                    media_type=event.file.content_type,
                    title=title,
                    business_domain=str(knowledge_domain.value),
                    knowledge_type=DocumentKnowledgeType(str(knowledge_type.value)),
                    access_scope=_split_labels(access_scope.value or "public"),
                    document_id=None,
                )
            except AppError as exc:
                ui.notify(exc.message, type="negative")
                return
            upload_result.clear()
            with upload_result:
                ui.badge(f"入库：{result.job_status}", color="positive")
                ui.label(
                    f"版本v{result.version.version_number} · "
                    f"SourceBlock {result.block_count} · Chunk {result.chunk_count}"
                ).classes("text-caption")
                if result.error_code:
                    ui.label(f"错误码：{result.error_code}").classes("text-negative")
            ui.notify("知识文件处理完成", type="positive")
            await refresh_documents()

        async def refresh_documents() -> None:
            try:
                documents = await knowledge_service.list_documents(actor=actor())
            except AppError as exc:
                ui.notify(exc.message, type="negative")
                return
            document_table.rows = [
                {
                    "id": item.id,
                    "title": item.title,
                    "domain": item.business_domain,
                    "type": item.knowledge_type,
                    "scope": ", ".join(item.access_scope),
                    "status": item.status,
                }
                for item in documents
            ]
            document_table.update()

        async def create_term() -> None:
            value = (term_input.value or "").strip()
            if not value:
                ui.notify("请输入领域词", type="warning")
                return
            try:
                result = await dictionary_service.create_candidate(
                    actor=actor(),
                    payload=DictionaryTermCreate(
                        term=value,
                        aliases=tuple(_split_labels(aliases_input.value or "")),
                        business_domain=BusinessDomain(str(term_domain.value)),
                        term_type=DictionaryTermType(str(term_type.value)),
                        frequency=int(term_frequency.value or 6000),
                        source_type=DictionarySourceType(str(term_source.value)),
                        source_reference=(source_reference.value or "").strip() or None,
                    ),
                )
            except (AppError, ValueError) as exc:
                message = exc.message if isinstance(exc, AppError) else str(exc)
                ui.notify(message, type="negative")
                return
            term_form_result.set_text(f"已写入：{result.term} · 状态 {result.status.value}")
            term_input.value = ""
            aliases_input.value = ""
            ui.notify("候选词已写入MySQL", type="positive")
            await refresh_terms()

        async def refresh_terms() -> None:
            try:
                terms = await dictionary_service.list_terms(
                    business_domain=None,
                    status=None,
                )
            except AppError as exc:
                ui.notify(exc.message, type="negative")
                return
            term_table.rows = [
                {
                    "id": item.id,
                    "term": item.term,
                    "aliases": "、".join(item.aliases) or "-",
                    "domain": item.business_domain.value,
                    "source": item.source_type.value,
                    "status": item.status.value,
                }
                for item in terms
            ]
            term_table.update()

        async def refresh_reviews() -> None:
            try:
                candidates = await dictionary_service.list_terms(
                    business_domain=None,
                    status=DictionaryTermStatus.CANDIDATE,
                )
            except AppError as exc:
                ui.notify(exc.message, type="negative")
                return
            review_list.clear()
            with review_list:
                if not candidates:
                    ui.label("当前没有待审核词条。").classes("text-grey-6")
                for item in candidates:
                    with ui.card().classes("w-full workbench-card"):
                        with ui.row().classes("w-full items-center justify-between"):
                            with ui.column().classes("gap-0"):
                                ui.label(item.term).classes("text-subtitle1 font-bold")
                                ui.label(
                                    f"{item.business_domain.value} · "
                                    f"{item.term_type.value} · {item.source_type.value} · "
                                    f"词频 {item.frequency}"
                                ).classes("text-caption text-grey-7")
                                if item.aliases:
                                    ui.label("别名：" + "、".join(item.aliases)).classes(
                                        "text-caption"
                                    )
                            with ui.row().classes("gap-2"):
                                ui.button(
                                    "通过",
                                    icon="check",
                                    color="positive",
                                    on_click=lambda _, term_id=item.id: review_term(term_id, True),
                                )
                                ui.button(
                                    "拒绝",
                                    icon="close",
                                    color="negative",
                                    on_click=lambda _, term_id=item.id: review_term(term_id, False),
                                ).props("outline")

        async def review_term(term_id: str, approved: bool) -> None:
            note = (review_note.value or "").strip()
            if not note:
                ui.notify("请输入审核意见", type="warning")
                return
            try:
                await dictionary_service.review(
                    actor=actor(),
                    term_id=term_id,
                    approved=approved,
                    review_note=note,
                )
            except AppError as exc:
                ui.notify(exc.message, type="negative")
                return
            ui.notify("审核结果已写入MySQL", type="positive")
            await refresh_reviews()
            await refresh_terms()

        async def publish_dictionary() -> None:
            note = (release_note.value or "").strip()
            if not note:
                ui.notify("请输入发布说明", type="warning")
                return
            try:
                version = await dictionary_service.publish(actor=actor(), release_note=note)
            except AppError as exc:
                ui.notify(exc.message, type="negative")
                return
            ui.notify(f"词典v{version.version_number}已发布", type="positive")
            await refresh_versions()
            await show_active_artifact()

        async def refresh_versions() -> None:
            try:
                versions = await dictionary_service.list_versions()
            except AppError as exc:
                ui.notify(exc.message, type="negative")
                return
            version_table.rows = [
                {
                    "id": item.id,
                    "version": f"v{item.version_number}",
                    "status": item.status.value,
                    "count": item.term_count,
                    "hash": item.content_sha256[:12] + "…",
                    "note": item.release_note or "-",
                }
                for item in versions
            ]
            version_table.update()

        async def show_active_artifact() -> None:
            try:
                artifact = await dictionary_service.active_artifact()
            except AppError as exc:
                ui.notify(exc.message, type="warning")
                return
            artifact_meta.set_text(
                f"v{artifact.version_number} · {artifact.term_count}词 · "
                f"SHA {artifact.content_sha256[:16]}…"
            )
            artifact_preview.value = artifact.artifact_content

        create_button.on_click(create_conversation)
        send_button.on_click(send)
        intent_button.on_click(classify_intent)
        question.on("keydown.enter", send)
        uploader.on_upload(upload_knowledge)
        refresh_documents_button.on_click(refresh_documents)
        create_term_button.on_click(create_term)
        refresh_terms_button.on_click(refresh_terms)
        refresh_review_button.on_click(refresh_reviews)
        publish_button.on_click(publish_dictionary)
        refresh_versions_button.on_click(refresh_versions)
        artifact_button.on_click(show_active_artifact)

    ui.run_with(
        fastapi_app,
        root=support_page,
        mount_path="/support",
        title="BiliSupport AI 企业客服工作台",
        language="zh-CN",
        storage_secret=storage_secret,
        show_welcome_message=False,
    )


def _render_overview(
    *,
    tabs: Tabs,
    destinations: tuple[tuple[str, str, str, str, Tab], ...],
) -> None:
    _section_heading(
        "企业智能客服能力中心",
        "统一进入客服问答、知识运营和词典发布；每项能力明确真实实现或Mock边界。",
    )
    with ui.row().classes("w-full gap-4"):
        for title, description, icon, status, destination in destinations:
            with ui.card().classes(
                "feature-card workbench-card w-full sm:w-[calc(50%-8px)] lg:w-[calc(33.333%-12px)]"
            ):
                with ui.row().classes("w-full justify-between items-start"):
                    ui.icon(str(icon), size="36px", color="primary")
                    ui.badge(str(status), color="positive")
                ui.label(str(title)).classes("text-h6 section-title")
                ui.label(str(description)).classes("text-body2 text-grey-7 grow")
                ui.button(
                    "进入功能",
                    icon="arrow_forward",
                    on_click=lambda _, target=destination: tabs.set_value(target),
                ).props("flat")


def _render_capabilities(*, intent_provider_name: str) -> None:
    _section_heading("当前能力与商业化边界", "用于演示和验收时区分真实链路与Mock模块。")
    rows = (
        ("智能客服会话", "真实", "MySQL持久化、Redis可选缓存、SSE流式响应"),
        (
            "意图识别",
            "Mock" if intent_provider_name == "mock" else "真实模型",
            "规则短路、结构化模型、风险和澄清策略",
        ),
        ("知识解析", "真实", "PDF、DOCX、Markdown、TXT和结构化FAQ"),
        ("混合检索", "真实", "Jieba BM25、Milvus Vector、RRF和Small-to-Big"),
        ("回答门禁", "真实", "策略v2、实体覆盖、一次补检索、拒答和澄清"),
        ("领域词典", "真实", "候选、审核、版本、SHA-256制品和回滚边界"),
        ("客服日志来源", "Mock", "只模拟候选输入，不读取真实用户日志"),
        ("人工坐席", "Mock", "只显示路由结果，不连接真实工单或坐席平台"),
    )
    with ui.grid(columns=2).classes("w-full gap-4"):
        for name, status, description in rows:
            with ui.card().classes("workbench-card"):
                with ui.row().classes("w-full justify-between items-center"):
                    ui.label(name).classes("text-subtitle1 font-bold")
                    ui.badge(
                        status,
                        color="positive" if status == "真实" or status == "真实模型" else "orange",
                    )
                ui.label(description).classes("text-body2 text-grey-7")


def _section_heading(title: str, description: str) -> None:
    with ui.column().classes("gap-1 mb-3"):
        ui.label(title).classes("text-h5 section-title")
        ui.label(description).classes("text-body2 text-grey-7")


def _render_intent(
    decision: IntentDecision,
    *,
    rule_id: str | None,
    applied_policy_ids: tuple[str, ...],
) -> None:
    with ui.row().classes("items-center gap-2"):
        ui.badge(f"路由：{decision.route.value}", color="primary")
        ui.badge(f"风险：{decision.risk.value}", color="secondary")
        ui.label(f"置信度：{decision.confidence:.2f}")
    ui.label(f"情绪：{decision.sentiment.value} · 来源：{decision.source.value}").classes(
        "text-caption"
    )
    if rule_id:
        ui.label(f"规则：{rule_id}").classes("text-caption text-grey-7")
    if applied_policy_ids:
        ui.label("兜底策略：" + "、".join(applied_policy_ids)).classes("text-caption text-grey-7")
    for item in decision.intents:
        ui.chip(f"{item.domain.value} + {item.action.value} ({item.confidence:.2f})")
    for entity in decision.entities:
        normalized = f" → {entity.normalized_value}" if entity.normalized_value else ""
        ui.label(f"{entity.type.value}: {entity.raw_value}{normalized}")
    if decision.needs_clarification:
        ui.label(f"需要澄清：{decision.clarification_question}").classes("text-orange")


def _routing_details(summary: CustomerServiceRouteSummary) -> str:
    details: list[str] = []
    retrieval = summary.retrieval
    classification_error = summary.classification_error
    if classification_error:
        details.append(f"意图识别失败：{classification_error}")
    if retrieval is not None:
        details.append(f"检索：{retrieval.mode.value} · 证据：{retrieval.evidence_count}条")
        if retrieval.policy is not None:
            details.append(
                f"策略：{retrieval.policy.policy_id} · 决策：{retrieval.policy.decision.value}"
            )
        if retrieval.coverage is not None:
            coverage = retrieval.coverage
            details.append(f"覆盖：{len(coverage.covered)}/{len(coverage.required)}")
            if coverage.missing:
                details.append("缺失：" + "、".join(coverage.missing))
        if retrieval.used_evidence_ids:
            details.append("实际引用：" + "、".join(retrieval.used_evidence_ids))
        if retrieval.citations:
            details.append(
                "候选证据：\n"
                + "\n".join(
                    f"- **[{item.evidence_id}] {item.document_title}**"
                    f"{_citation_location(item.heading_path, item.page_numbers)}："
                    f"{item.excerpt or '暂无摘要'}"
                    for item in retrieval.citations
                )
            )
        if retrieval.verification is not None:
            verification = retrieval.verification
            details.append(
                f"声明校验：{verification.decision.value} "
                f"（支持{verification.supported_count}、部分{verification.partial_count}、"
                f"不支持{verification.unsupported_count}、冲突{verification.conflict_count}、"
                f"未知{verification.unknown_count}）"
            )
            details.append(
                "校验器："
                f"{verification.provider} · {verification.mode.value} · "
                f"{verification.model or '规则门禁'} · {verification.latency_ms:.0f}ms"
            )
            if verification.error_code is not None:
                details.append(f"校验异常：{verification.error_code}")
        if retrieval.grounding_error_code:
            details.append(f"回答校验：{retrieval.grounding_error_code}")
        if retrieval.error_code:
            details.append(f"知识服务：{retrieval.error_code}")
    return "\n\n".join(details)


def _citation_location(
    heading_path: tuple[str, ...],
    page_numbers: tuple[int, ...],
) -> str:
    """把Word/Markdown章节和PDF页码压缩成可读定位文本。"""

    parts: list[str] = []
    if heading_path:
        parts.append(" > ".join(heading_path))
    if page_numbers:
        parts.append("第" + "、".join(str(item) for item in page_numbers) + "页")
    return " · " + " · ".join(parts) if parts else ""


def _split_labels(value: str) -> list[str]:
    return list(
        dict.fromkeys(item.strip() for item in value.replace("，", ",").split(",") if item.strip())
    )
