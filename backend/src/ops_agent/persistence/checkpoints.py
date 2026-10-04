"""PostgreSQL-backed LangGraph checkpoints isolated from business tables."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg import AsyncConnection, sql
from psycopg.rows import DictRow, dict_row


@asynccontextmanager
async def open_postgres_checkpointer(
    database_url: str,
    *,
    schema: str = "langgraph_checkpoint",
    setup: bool = False,
) -> AsyncIterator[AsyncPostgresSaver]:
    """Open a saver whose unqualified tables are confined to ``schema``.

    The connection is intentionally independent from SQLAlchemy business sessions.
    LangGraph owns the internal table format; application repositories never query it.
    """
    if not schema.isidentifier() or not schema.isascii() or len(schema) > 63:
        raise ValueError("checkpoint schema must be a valid ASCII PostgreSQL identifier")

    connection: AsyncConnection[DictRow] = await AsyncConnection.connect(
        database_url,
        autocommit=True,
        prepare_threshold=0,
        row_factory=dict_row,
    )
    try:
        await connection.execute(
            sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(schema))
        )
        await connection.execute(
            sql.SQL("SET search_path TO {}, pg_catalog").format(sql.Identifier(schema))
        )
        checkpointer = AsyncPostgresSaver(connection)
        if setup:
            await checkpointer.setup()
        yield checkpointer
    finally:
        await connection.close()
