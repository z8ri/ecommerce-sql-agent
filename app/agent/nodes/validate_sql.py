"""
SQL 校验节点

负责在真正执行查询前，用数据库解析一次生成的 SQ
校验结果不在这里决定流程走向，而是通过 state["error"] 交给 graph.py 的条件边判断
"""

from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.guard_support import guard
from app.agent.state import DataAgentState
from app.conf.app_config import app_config
from app.core.log import logger
from app.repositories.mysql.dw.dw_mysql_repository import DWMySQLRepository


async def validate_sql(state: DataAgentState, runtime: Runtime[DataAgentContext]):
    """校验 SQL，并返回 error 字段控制后续条件分支"""

    writer = runtime.stream_writer
    step = "校验SQL"
    writer({"type": "progress", "step": step, "status": "running"})

    try:
        # 读取 generate_sql 或 correct_sql 写入状态的候选 SQL
        sql = state["sql"]

        # 先做确定性的安全检查：不是单条只读查询、访问了白名单外的表、含危险函数的 SQL
        # 直接拒绝，不进入后面的校验和修正；通过的 SQL 以语法树重新生成的版本为准（已补 LIMIT）
        updates = {}
        if app_config.agent.sql_guard:
            checked = await guard(sql, runtime)
            if not checked.ok:
                logger.warning(f"SQL 被安全检查拒绝：{checked.reason}；SQL：{sql!r}")
                writer({"type": "progress", "step": step, "status": "error"})
                return {
                    "blocked": True,
                    "error": f"SQL安全检查未通过：{checked.reason}",
                }
            if checked.sql != sql:
                logger.info(f"SQL 已按安全规则改写：{checked.rewrites}")
            sql = checked.sql
            updates["sql"] = sql

        # SQL 可用性必须交给真实数仓判断，这里从运行时上下文取 DW Repository
        dw_mysql_repository: DWMySQLRepository = runtime.context["dw_mysql_repository"]

        try:
            # validate 内部使用 explain <sql>，只关心数据库能否成功解析这条 SQL
            await dw_mysql_repository.validate(sql)
            writer({"type": "progress", "step": step, "status": "success"})
            logger.info("SQL语法正确")
            return {"error": None, **updates}
        except Exception as e:
            # 不抛出异常中断图执行，而是把错误写入状态，供条件分支进入 correct_sql
            logger.info(f"SQL语法错误：{str(e)}")
            writer({"type": "progress", "step": step, "status": "success"})
            return {"error": str(e), **updates}

    except Exception as e:
        logger.error(f"{step} failed: {e}")
        writer({"type": "progress", "step": step, "status": "error"})
        raise
