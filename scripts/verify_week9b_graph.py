"""通过正式会话API执行一次9B，并从MongoDB恢复各节点状态。"""

from __future__ import annotations

import asyncio
import json
from uuid import uuid4

from fastapi.testclient import TestClient
from langchain_core.runnables import RunnableConfig

from bili_support.core.config import get_settings
from bili_support.main import create_app


def main() -> None:
    """创建会话、发送知识问题，并按相同执行分区读取最终Checkpoint。"""

    settings = get_settings()
    if not settings.graph_checkpoint_enabled:
        raise RuntimeError("enable graph checkpoint before running this verifier")
    application = create_app(settings)
    request_id = f"week9b-smoke-{uuid4()}"
    headers = {
        "Authorization": f"Bearer {settings.api_token.get_secret_value()}",
        "X-User-ID": "demo-user",
        "X-User-Name": "demo-user",
        "X-Request-ID": request_id,
    }
    with TestClient(application) as client:
        created = client.post(
            "/api/v1/conversations",
            json={"title": "9B真实Graph验收"},
            headers=headers,
        )
        created.raise_for_status()
        thread_id = created.json()["data"]["thread_id"]
        response = client.post(
            f"/api/v1/conversations/{thread_id}/messages",
            json={"content": "大会员支付成功后多久生效？"},
            headers=headers,
        )
        response.raise_for_status()
        body = response.json()["data"]
        config: RunnableConfig = {
            "configurable": {"thread_id": f"{thread_id}:{request_id}"}
        }
        snapshot = asyncio.run(
            application.state.customer_service_graph.aget_state(config)
        )

    print(
        json.dumps(
            {
                "conversation_thread_id": thread_id,
                "checkpoint_thread_id": f"{thread_id}:{request_id}",
                "route": body["routing"]["target"],
                "classification_error": body["routing"].get(
                    "classification_error"
                ),
                "current_node": snapshot.values.get("current_node"),
                "visited_nodes": snapshot.values.get("visited_nodes"),
                "answer_preview": body["answer"][:120],
                "evidence_count": (
                    body["routing"].get("retrieval") or {}
                ).get("evidence_count"),
                "used_evidence_ids": (
                    body["routing"].get("retrieval") or {}
                ).get("used_evidence_ids"),
                "verification_decision": (
                    (body["routing"].get("retrieval") or {}).get("verification")
                    or {}
                ).get("decision"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
