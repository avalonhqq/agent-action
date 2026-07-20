# 本地 MySQL 与 Redis 接入记录

> 接入日期：2026-07-20。真实本地密码只保存在被 Git 忽略的 `.env`，本文不记录密码。

## 当前连接

- MySQL：`127.0.0.1:3306`，MySQL 8.0.42，数据库 `bili_support`，字符集 `utf8mb4`。
- Redis：`127.0.0.1:6379`，DB 0，无密码。
- SQLAlchemy 驱动：`mysql+aiomysql`。
- Redis 客户端：`redis.asyncio`。

## 数据职责

MySQL 是事实存储：用户、会话、消息、模型调用和 Alembic 版本都以 MySQL 为准。

Redis 只缓存模型可见的会话历史：

```text
bili-support:conversation:{thread_id}:history
```

值是最小化的 `role/content` JSON，默认 TTL 900 秒且最多保留最近 100 条。缓存未命中或 Redis 异常时回退 MySQL；Redis 不能成为消息事实来源。

## 创建与迁移

推荐方式：

```powershell
cd C:\workspace\agent-action
.venv\Scripts\python.exe -m alembic upgrade head
```

已经在本地执行成功，当前 revision 为 `20260719_0001`。完整建表 SQL 见 [mysql-schema.sql](mysql-schema.sql)。

## 当前表

| 表 | 作用 |
|---|---|
| `users` | 外部用户与显示名称 |
| `conversations` | 用户拥有的 Thread |
| `messages` | user/assistant 历史消息 |
| `model_calls` | 模型、Prompt、Token、耗时、状态和消息关联 |
| `alembic_version` | 当前数据库迁移版本 |

## 就绪检查

`GET /ready` 执行 MySQL `SELECT 1` 和 Redis `PING`。本地 `.env` 将 Redis 标记为 required，因此任一依赖不可用都会返回安全的 503；普通缓存读写仍有 MySQL 回退逻辑，避免运行中 Redis 短暂抖动破坏会话事实。

真实应用链路已验证：`/ready` 返回 database/redis ready，创建会话返回 201，发送消息返回 200；MySQL 同时产生 Conversation、两条 Message 和一条 ModelCall，Redis 产生带 TTL 的历史 key。校验数据随后已清理。

## 接入时发现并修复的问题

SQLite 支持 INSERT RETURNING，因此测试中 `created_at/updated_at` 会自动出现在 ORM 对象上；MySQL 依赖数据库默认时间且不会用同样方式回填。首次真实验证出现“数据库已插入、响应序列化时对象已脱离 Session”的 500。

修复方式是在事务关闭前显式 `session.refresh(conversation)`，再提交和返回。这个问题说明 SQLite 测试不能替代真实 MySQL 集成验收。

## 安全边界

- `.env` 已被 `.gitignore` 排除。
- `.env.example` 只给出占位示例，不包含真实密码。
- README 和日志不输出数据库密码或完整带密钥 URL。
- 当前 root 账号只适合本地开发；生产应创建最小权限应用账号并通过 Secret Manager 注入。
