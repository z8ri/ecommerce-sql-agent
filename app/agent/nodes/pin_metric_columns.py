"""
指标依赖字段固定节点

表过滤（filter_table）由大模型挑选“回答问题需要哪些字段”，它和指标过滤（filter_metric）并行执行，
所以并不知道最终会选中哪个指标。评测发现这会导致一个系统性错误：问 GMV 时，GMV 口径依赖的
fact_order.gross_amount 被当成“用不上的字段”剔除，模型只能用旁边的 pay_amount 凑数（口径错误）。

这个节点在两条过滤线汇合后执行，用确定性逻辑把选中指标声明依赖的字段补回上下文：
- 字段已经在上下文里：什么也不做
- 字段所在的表还在：只补这个字段
- 字段所在的表已被剔除：补回整张表，并带上它的主外键字段，保证还能 join
"""

from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.state import ColumnInfoState, DataAgentState, TableInfoState
from app.conf.app_config import app_config
from app.core.log import logger
from app.entities.column_info import ColumnInfo


def to_state(column_info: ColumnInfo) -> ColumnInfoState:
    return ColumnInfoState(
        name=column_info.name,
        type=column_info.type,
        role=column_info.role,
        examples=column_info.examples,
        description=column_info.description,
        alias=column_info.alias,
    )


async def pin_metric_columns(state: DataAgentState, runtime: Runtime[DataAgentContext]):
    """把选中指标依赖的字段补回表上下文"""

    writer = runtime.stream_writer
    step = "补齐指标依赖字段"
    writer({"type": "progress", "step": step, "status": "running"})

    try:
        table_infos: list[TableInfoState] = state["table_infos"]
        metric_infos = state["metric_infos"]
        if not app_config.agent.pin_metric_columns:
            writer({"type": "progress", "step": step, "status": "success"})
            return {}

        meta = runtime.context["meta_mysql_repository"]
        tables = {t["name"]: t for t in table_infos}
        added: list[str] = []

        for metric in metric_infos:
            for column_id in metric["relevant_columns"]:
                table_name, column_name = column_id.split(".", 1)
                table = tables.get(table_name)
                if table and any(c["name"] == column_name for c in table["columns"]):
                    continue

                column_info = await meta.get_column_info_by_id(column_id)
                if column_info is None:
                    logger.warning(
                        f"指标 {metric['name']} 依赖的字段不存在：{column_id}"
                    )
                    continue

                if table is None:
                    # 整张表都被剔除了：补回表，并带上主外键字段以便 join
                    table_info = await meta.get_table_info_by_id(table_name)
                    key_columns = await meta.get_key_columns_by_table_id(table_name)
                    table = TableInfoState(
                        name=table_info.name,
                        role=table_info.role,
                        description=table_info.description,
                        columns=[to_state(c) for c in key_columns],
                    )
                    tables[table_name] = table
                    table_infos.append(table)

                if not any(c["name"] == column_name for c in table["columns"]):
                    table["columns"].append(to_state(column_info))
                added.append(column_id)

        if added:
            logger.info(f"补回指标依赖字段：{added}")
        writer({"type": "progress", "step": step, "status": "success"})
        return {"table_infos": table_infos}

    except Exception as e:
        logger.error(f"{step} failed: {e}")
        writer({"type": "progress", "step": step, "status": "error"})
        raise
