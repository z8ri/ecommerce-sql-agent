"""
SQL 执行节点

负责执行最终 SQL，并记录查询结果。
它是当前 SQL 闭环的结束节点，执行完成后流程进入 END。
"""

from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.guard_support import guard
from app.agent.state import DataAgentState
from app.conf.app_config import app_config
from app.core.log import logger


async def run_sql(state: DataAgentState, runtime: Runtime[DataAgentContext]):
    """执行 SQL 并产出最终问数结果"""

    writer = runtime.stream_writer
    step = "执行SQL"
    writer({"type": "progress", "step": step, "status": "running"})

    try:
        # 这里拿到的可能是 generate_sql 直接通过校验的 SQL，也可能是 correct_sql 覆盖后的 SQL
        sql = state["sql"]
        dw_mysql_repository = runtime.context["dw_mysql_repository"]

        # 执行前再检查一次：旧流程里修正后的 SQL 不会回到校验节点
        if app_config.agent.sql_guard:
            checked = await guard(sql, runtime)
            if not checked.ok:
                logger.warning(
                    f"执行前 SQL 被安全检查拒绝：{checked.reason}；SQL：{sql!r}"
                )
                writer({"type": "progress", "step": step, "status": "error"})
                writer(
                    {
                        "type": "error",
                        "message": f"请求被安全策略拒绝：{checked.reason}",
                    }
                )
                return {
                    "blocked": True,
                    "error": f"SQL安全检查未通过：{checked.reason}",
                }
            sql = checked.sql

        # 真实数据库访问统一封装在仓储层，节点只负责从状态取 SQL 并触发执行
        if not app_config.agent.self_correct:
            result = await dw_mysql_repository.run(sql)
            logger.info(f"SQL执行结果：{result}")
            writer({"type": "progress", "step": step, "status": "success"})
            writer({"type": "result", "data": result})
            return

        # 自纠错模式：执行出错不直接失败，而是把错误交给修复节点；结果先不发给前端，
        # 等 verify_result 复核通过（或修正次数用完）再发送
        try:
            result = await dw_mysql_repository.run(sql)
        except Exception as e:
            logger.info(f"SQL执行出错：{e}")
            writer({"type": "progress", "step": step, "status": "success"})
            return {"error": f"SQL执行出错：{e}", "result": None}
        logger.info(f"SQL执行结果：{result}")
        writer({"type": "progress", "step": step, "status": "success"})
        return {"result": result, "error": None}

    except Exception as e:
        logger.error(f"{step} failed: {e}")
        writer({"type": "progress", "step": step, "status": "error"})
        raise
