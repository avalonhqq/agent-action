"""通过正式应用依赖验证两轮省略问句、持久化主题与可解释接口。"""

from __future__ import annotations

import json
from uuid import uuid4

from fastapi.testclient import TestClient

from bili_support.core.config import get_settings
from bili_support.main import create_app


def main() -> None:
    """使用当前.env依次询问完整问题和价格追问。"""

    settings = get_settings()
    headers = {
        "Authorization": f"Bearer {settings.api_token.get_secret_value()}",
        "X-User-ID": "demo-user",
        "X-User-Name": "demo-user",
    }
    with TestClient(create_app(settings)) as client:
        created = client.post(
            "/api/v1/conversations",
            json={"title": "多轮上下文真实验收"},
            headers=headers,
        )
        created.raise_for_status()
        thread_id = created.json()["data"]["thread_id"]

        results: list[dict[str, object]] = []
        latest_request_id = ""
        for question in ("大会员能做什么", "多少钱"):
            latest_request_id = f"context-{uuid4()}"
            response = client.post(
                f"/api/v1/conversations/{thread_id}/messages",
                json={"content": question},
                headers={**headers, "X-Request-ID": latest_request_id},
            )
            response.raise_for_status()
            data = response.json()["data"]
            results.append(
                {
                    "question": question,
                    "context_resolution": data["context_resolution"],
                    "route": data["routing"]["target"],
                    "rule_id": data["routing"].get("rule_id"),
                    "answer_preview": data["answer"][:120],
                }
            )

        context = client.get(
            f"/api/v1/conversations/{thread_id}/context",
            headers=headers,
        )
        context.raise_for_status()
        timeline = client.get(
            f"/api/v1/conversations/{thread_id}/executions/"
            f"{latest_request_id}/timeline",
            headers=headers,
        )
        timeline.raise_for_status()

    print(
        json.dumps(
            {
                "thread_id": thread_id,
                "turns": results,
                "persisted_context": context.json()["data"],
                "latest_timeline": timeline.json()["data"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
