"""对本地MongoDB执行一次真实LangGraph写入与跨Saver恢复验收。"""

from __future__ import annotations

import asyncio
import json
from uuid import uuid4

from langchain_core.runnables import RunnableConfig

from bili_support.core.config import get_settings
from bili_support.graph.checkpoints import MongoGraphCheckpointStore
from bili_support.graph.state import create_graph_input
from bili_support.graph.workflow import build_week9a_graph


def create_store() -> MongoGraphCheckpointStore:
    """使用与应用完全相同的配置创建Checkpoint存储。"""

    settings = get_settings()
    return MongoGraphCheckpointStore(
        uri=settings.graph_checkpoint_mongodb_uri.get_secret_value(),
        database=settings.graph_checkpoint_database,
        checkpoint_collection=settings.graph_checkpoint_collection,
        writes_collection=settings.graph_checkpoint_writes_collection,
        ttl_seconds=settings.graph_checkpoint_ttl_seconds,
        connect_timeout_seconds=settings.graph_checkpoint_connect_timeout_seconds,
        encryption_key=(
            settings.graph_checkpoint_encryption_key.get_secret_value()
            if settings.graph_checkpoint_encryption_key is not None
            else None
        ),
    )


async def main() -> None:
    """写入一个线程，关闭连接，再用新连接读取同一线程的最新快照。"""

    thread_id = f"checkpoint-smoke-{uuid4()}"
    config: RunnableConfig = {"configurable": {"thread_id": thread_id}}

    writer = create_store()
    await writer.start()
    graph = build_week9a_graph(checkpointer=writer.saver)
    result = await graph.ainvoke(
        create_graph_input(
            request_id=f"request-{uuid4()}",
            thread_id=thread_id,
            user_id="checkpoint-verifier",
            question="大会员开通后多久生效？",
        ),
        config=config,
    )
    checkpoint_count = await asyncio.to_thread(
        writer.saver.checkpoint_collection.count_documents,
        {"thread_id": thread_id},
    )
    indexes = await asyncio.to_thread(
        writer.saver.checkpoint_collection.index_information
    )
    newest_document = await asyncio.to_thread(
        writer.saver.checkpoint_collection.find_one,
        {"thread_id": thread_id},
        sort=[("checkpoint_id", -1)],
    )
    await writer.close()

    # 新建客户端和Graph，证明读到的是MongoDB持久化结果，不是进程内对象。
    reader = create_store()
    await reader.start()
    restored_graph = build_week9a_graph(checkpointer=reader.saver)
    snapshot = await restored_graph.aget_state(config)
    await reader.close()

    print(
        json.dumps(
            {
                "thread_id": thread_id,
                "run_status": result["status"],
                "checkpoint_documents": checkpoint_count,
                "restored_current_node": snapshot.values.get("current_node"),
                "restored_question": snapshot.values.get("question"),
                "index_names": sorted(indexes),
                "ttl_seconds": indexes.get("created_at_1", {}).get(
                    "expireAfterSeconds"
                ),
                "payload_encrypted": bool(
                    newest_document
                    and "+aes" in str(newest_document.get("type", ""))
                ),
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
