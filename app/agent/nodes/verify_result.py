"""
结果语义复核节点

EXPLAIN 只能发现语法错误。评测显示，首次生成就通过 EXPLAIN 的 SQL 里仍有约两成答案是错的：
口径用错、多张事实表直接 JOIN 造成重复计算、时间范围缺年份……这些 SQL 都能顺利执行。
这个节点在 SQL 执行之后检查“这个结果可信吗”，分两层：

1. 确定性规则：结果为空、单行全 NULL。不花大模型调用，直接判定有问题。
2. 大模型复核：把问题、指标口径、SQL 和结果摘要交给模型，对照口径逐项检查。
   提示词要求“拿不准就判通过”，避免误报造成不必要的改写。

发现问题时把意见写入 state["error"]，由图路由回 repair_sql；没有问题，或修正次数用完，
就把结果发给前端并结束。
"""

import yaml
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import PromptTemplate
from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.llm import llm
from app.agent.state import DataAgentState
from app.conf.app_config import app_config
from app.core.log import logger
from app.prompt.prompt_loader import load_prompt

PREVIEW_ROWS = 10


def dump(data) -> str:
    return yaml.dump(data, allow_unicode=True, sort_keys=False)


def rule_based_issues(result: list[dict]) -> list[str]:
    """不需要大模型的确定性检查"""
    if not result:
        return [
            "查询结果为空。请检查过滤条件：字段取值的写法是否和字段示例值一致，"
            "时间范围（含年份）是否在数据覆盖范围内，是否多加了不必要的条件。"
        ]
    if len(result) == 1 and all(v is None for v in result[0].values()):
        return [
            "查询结果只有一行且全部为 NULL，说明过滤条件没有命中任何数据，请检查过滤条件。"
        ]
    return []


def summarize(result: list[dict]) -> str:
    return dump(
        {
            "row_count": len(result),
            "columns": list(result[0].keys()) if result else [],
            f"first_{PREVIEW_ROWS}_rows": result[:PREVIEW_ROWS],
        }
    )


async def verify_result(state: DataAgentState, runtime: Runtime[DataAgentContext]):
    """复核 SQL 的执行结果；通过或修正次数用完时输出最终结果"""

    writer = runtime.stream_writer
    step = "复核结果"
    writer({"type": "progress", "step": step, "status": "running"})

    try:
        result = state["result"]
        repairs = state.get("repairs", 0)
        can_repair = repairs < app_config.agent.max_repairs

        issues = rule_based_issues(result)
        if not issues:
            prompt = PromptTemplate(
                template=load_prompt("verify_result"),
                input_variables=[
                    "query",
                    "table_infos",
                    "metric_infos",
                    "date_info",
                    "sql",
                    "result_summary",
                ],
            )
            chain = prompt | llm | JsonOutputParser()
            verdict = await chain.ainvoke(
                {
                    "query": state["query"],
                    "table_infos": dump(state["table_infos"]),
                    "metric_infos": dump(state["metric_infos"]),
                    "date_info": dump(state["date_info"]),
                    "sql": state["sql"],
                    "result_summary": summarize(result),
                }
            )
            if verdict.get("verdict") == "fix":
                issues = [str(i) for i in verdict.get("issues", [])]

        writer({"type": "progress", "step": step, "status": "success"})
        if issues and can_repair:
            logger.info(f"结果复核未通过，进入修正：{issues}")
            return {"error": "结果复核未通过：" + "；".join(issues)}

        if issues:
            logger.warning(f"修正次数已用完，结果仍有疑点：{issues}")
        writer({"type": "result", "data": result})
        return {"error": None, "verified": not issues}

    except Exception as e:
        logger.error(f"{step} failed: {e}")
        writer({"type": "progress", "step": step, "status": "error"})
        raise
