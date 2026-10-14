"""
电商问数 Agent 状态定义

State 是 LangGraph 各节点之间传递和更新的共享数据
本章在用户原始问题之外，新增关键词列表和三路召回结果
并把召回到的实体整理成后续提示词更容易消费的表信息和指标信息
SQL 生成闭环会继续写入候选 SQL 以及校验错误信息，用于控制校正或执行分支
"""

from typing import TypedDict

from app.entities.column_info import ColumnInfo
from app.entities.metric_info import MetricInfo
from app.entities.value_info import ValueInfo


class MetricInfoState(TypedDict):
    """面向 SQL 生成提示词的指标信息"""

    name: str
    description: str
    # 指标依赖的字段 id，用来提示模型不要脱离业务口径随意计算
    relevant_columns: list[str]
    alias: list[str]


class ColumnInfoState(TypedDict):
    """表上下文中的字段信息"""

    name: str
    type: str
    role: str
    # 字段真实样例值，尤其用于辅助 where 条件里的枚举值选择
    examples: list
    description: str
    alias: list[str]


class TableInfoState(TypedDict):
    """SQL 生成阶段真正传给模型的表结构上下文"""

    name: str
    role: str
    description: str
    columns: list[ColumnInfoState]


class DateInfoState(TypedDict):
    """SQL 生成阶段使用的当前日期上下文"""

    date: str
    weekday: str
    quarter: str
    # 问题里的相对时间表达经程序确定的含义，见 time_resolver
    resolved: list[dict]


class DBInfoState(TypedDict):
    """SQL 生成阶段使用的数据库环境信息"""

    dialect: str
    version: str


class DataAgentState(TypedDict):
    """一次问数链路中的核心状态"""

    query: str  # 用户输入的查询
    keywords: list[str]  # 抽取的关键词
    retrieved_column_infos: list[ColumnInfo]  # 检索到的字段信息
    retrieved_metric_infos: list[MetricInfo]  # 检索到的指标信息
    retrieved_value_infos: list[ValueInfo]  # 检索到的取值信息

    table_infos: list[TableInfoState]  # 合并和补齐后的表结构上下文
    metric_infos: list[MetricInfoState]  # 合并后的指标上下文
    date_info: DateInfoState  # 当前日期 星期和季度信息
    db_info: DBInfoState  # 数据库方言和版本信息

    sql: str  # 生成或校正后的SQL

    error: str  # 校验SQL时出现的错误信息；自纠错模式下也承载执行错误和结果复核意见

    # 以下字段只在自纠错循环模式（agent.self_correct）下使用
    result: list[dict]  # 最近一次 SQL 的执行结果
    repairs: int  # 已经修正的次数
    history: list[dict]  # 此前失败的尝试（SQL 和反馈），避免重复同样的错误
    verified: bool  # 最终结果是否通过了语义复核
    blocked: bool  # SQL 安全检查未通过，请求被拒绝
