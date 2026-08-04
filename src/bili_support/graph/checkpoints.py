"""LangGraph的MongoDB Checkpoint生命周期边界。

MySQL继续保存用户、会话、消息和知识等业务事实；本模块只保存Graph执行快照与
pending writes。两类数据生命周期和写入模式不同，因此不混在同一Repository中。
"""

from __future__ import annotations

import asyncio

from langgraph.checkpoint.mongodb import MongoDBSaver
from langgraph.checkpoint.serde.encrypted import EncryptedSerializer
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from pymongo import MongoClient


class MongoGraphCheckpointStore:
    """拥有PyMongo客户端和MongoDBSaver，并负责启动探测与释放。

    当前官方Saver的异步方法通过线程池包装同步PyMongo调用；因此初始化、探测和
    关闭也显式放入工作线程，避免阻塞FastAPI事件循环。
    """

    def __init__(
        self,
        *,
        uri: str,
        database: str,
        checkpoint_collection: str = "checkpoints",
        writes_collection: str = "checkpoint_writes",
        ttl_seconds: int = 604800,
        connect_timeout_seconds: float = 5.0,
        encryption_key: str | None = None,
    ) -> None:
        self._uri = uri
        self._database = database
        self._checkpoint_collection = checkpoint_collection
        self._writes_collection = writes_collection
        self._ttl_seconds = ttl_seconds
        self._connect_timeout_ms = int(connect_timeout_seconds * 1000)
        self._encryption_key = encryption_key
        self._client: MongoClient[dict[str, object]] | None = None
        self._saver: MongoDBSaver | None = None

    @property
    def started(self) -> bool:
        """连接与Saver是否已成功初始化。"""

        return self._saver is not None

    @property
    def saver(self) -> MongoDBSaver:
        """返回已启动的Saver；禁止在连接检查前编译持久化Graph。"""

        if self._saver is None:
            raise RuntimeError("MongoDB graph checkpoint store is not started")
        return self._saver

    async def start(self) -> None:
        """连接Replica Set、执行ping并创建Saver所需索引。"""

        if self._saver is not None:
            return
        await asyncio.to_thread(self._start_sync)

    def _start_sync(self) -> None:
        client: MongoClient[dict[str, object]] = MongoClient(
            self._uri,
            serverSelectionTimeoutMS=self._connect_timeout_ms,
            connectTimeoutMS=self._connect_timeout_ms,
            appname="bili-support-langgraph",
        )
        try:
            client.admin.command("ping")
            hello = client.admin.command("hello")
            if not hello.get("setName"):
                raise RuntimeError("MongoDB checkpoint storage requires a replica set")
            strict_serializer = JsonPlusSerializer(
                allowed_msgpack_modules={
                    ("bili_support.graph.state", "GraphRunStatus"),
                    ("bili_support.graph.state", "GraphInputStatus"),
                    ("bili_support.graph.state", "GraphNextAction"),
                    ("bili_support.graph.state", "GraphErrorCode"),
                }
            )
            serializer = (
                EncryptedSerializer.from_pycryptodome_aes(
                    serde=strict_serializer,
                    key=self._encryption_key.encode(),
                )
                if self._encryption_key
                else strict_serializer
            )
            saver = MongoDBSaver(
                client,
                db_name=self._database,
                checkpoint_collection_name=self._checkpoint_collection,
                writes_collection_name=self._writes_collection,
                ttl=self._ttl_seconds,
                # 严格类型白名单防止任意类型恢复；配置密钥后再使用AES-EAX加密载荷。
                serde=serializer,
            )
        except Exception:
            client.close()
            raise
        self._client = client
        self._saver = saver

    async def ping(self) -> None:
        """验证MongoDB仍可服务，供/readiness使用。"""

        if self._client is None:
            raise RuntimeError("MongoDB graph checkpoint store is not started")
        await asyncio.to_thread(self._client.admin.command, "ping")

    async def close(self) -> None:
        """释放连接池；可重复调用。"""

        client = self._client
        self._client = None
        self._saver = None
        if client is not None:
            await asyncio.to_thread(client.close)
