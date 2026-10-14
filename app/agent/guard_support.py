"""
把 SQL 安全检查接入 Agent 节点

表白名单来自元数据库里登记的表，进程内缓存一份。
校验节点和执行节点都会调用：校验节点负责尽早拒绝并让后续节点拿到改写后的 SQL，
执行节点在真正执行前再检查一次（修正流程、旧流程都可能产出没经过校验节点的 SQL）。
检查是幂等的：已经补过 LIMIT 的 SQL 再检查一遍不会再改动。
"""

from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.sql_guard import GuardResult, check_sql
from app.conf.app_config import app_config

_allowed_tables: set[str] | None = None


async def allowed_tables(runtime: Runtime[DataAgentContext]) -> set[str]:
    global _allowed_tables
    if _allowed_tables is None:
        meta = runtime.context["meta_mysql_repository"]
        _allowed_tables = set(await meta.list_table_names())
    return _allowed_tables


async def guard(sql: str, runtime: Runtime[DataAgentContext]) -> GuardResult:
    return check_sql(sql, await allowed_tables(runtime), app_config.agent.max_rows)
