"""
SQL 修复节点（自纠错循环）

和旧的 correct_sql 的区别：
- 修复之后会重新回到 validate_sql 校验，而不是直接执行
- 反馈来源不只是 EXPLAIN 报错，还包括执行错误和结果语义复核意见
- 提示词不要求“最小改动”，允许为了修正口径或重复计算调整 SQL 结构，
  并明确禁止通过删除 JOIN 条件来让 SQL 通过（旧版就是这样把错误 SQL 变成“能跑但不对”）
- 会带上此前失败的尝试，避免循环里反复犯同一个错
"""

import yaml
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import PromptTemplate
from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.llm import llm
from app.agent.state import DataAgentState
from app.agent.time_resolver import TIME_RULES
from app.conf.app_config import app_config
from app.core.log import logger
from app.prompt.prompt_loader import load_prompt


def dump(data) -> str:
    return yaml.dump(data, allow_unicode=True, sort_keys=False)


async def repair_sql(state: DataAgentState, runtime: Runtime[DataAgentContext]):
    """根据校验错误、执行错误或结果复核意见修复 SQL"""

    writer = runtime.stream_writer
    repairs = state.get("repairs", 0) + 1
    step = f"修正SQL（第{repairs}次）"
    writer({"type": "progress", "step": step, "status": "running"})

    try:
        history = state.get("history", [])
        prompt = PromptTemplate(
            template=load_prompt("repair_sql"),
            input_variables=[
                "table_infos",
                "metric_infos",
                "date_info",
                "db_info",
                "query",
                "sql",
                "error",
                "history",
                "time_rules",
            ],
        )
        chain = prompt | llm | StrOutputParser()
        result = await chain.ainvoke(
            {
                "table_infos": dump(state["table_infos"]),
                "metric_infos": dump(state["metric_infos"]),
                "date_info": dump(state["date_info"]),
                "db_info": dump(state["db_info"]),
                "query": state["query"],
                "sql": state["sql"],
                "error": state["error"],
                "history": dump(history) if history else "无",
                "time_rules": TIME_RULES if app_config.agent.resolve_time else "",
            }
        )
        logger.info(f"第{repairs}次修正后的SQL：{result}")
        writer({"type": "progress", "step": step, "status": "success"})
        return {
            "sql": result,
            "repairs": repairs,
            "history": history + [{"sql": state["sql"], "feedback": state["error"]}],
            "error": None,
        }
    except Exception as e:
        logger.error(f"{step} failed: {e}")
        writer({"type": "progress", "step": step, "status": "error"})
        raise
