"""Migration smoke tests against an isolated SQLite database."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from alembic import command
from alembic.config import Config

from bili_support.core.config import reset_settings


def test_initial_migration_is_repeatable(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "migration.db"
    monkeypatch.setenv(
        "BILI_SUPPORT_DATABASE_URL",
        f"sqlite+aiosqlite:///{database_path.as_posix()}",
    )
    reset_settings()
    config = Config("alembic.ini")

    command.upgrade(config, "head")
    command.upgrade(config, "head")

    with sqlite3.connect(database_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        operation_column = next(
            row
            for row in connection.execute("PRAGMA table_info(model_calls)")
            if row[1] == "operation"
        )
    reset_settings()

    assert {
        "users",
        "conversations",
        "messages",
        "model_calls",
        "knowledge_documents",
        "knowledge_document_versions",
        "knowledge_ingestion_jobs",
        "knowledge_source_blocks",
        "knowledge_chunks",
    } <= tables
    assert revision == ("20260728_0004",)
    assert operation_column[2] == "VARCHAR(64)"
