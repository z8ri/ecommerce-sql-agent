"""
SQL 安全检查

大模型生成的 SQL 是不可信输入：用户可以在问题里诱导它写出修改数据的语句，也可能是提示词注入。
基线里这条 SQL 只经过 EXPLAIN（对 DELETE 也能通过）就被全权限账号直接执行。

这里用 sqlglot 把 SQL 解析成语法树，做确定性检查，不依赖大模型的自觉：

- 必须恰好是一条查询语句（SELECT / UNION / WITH ... SELECT），多语句、写操作、DDL、
  SET / USE / GRANT / 调用存储过程、SELECT ... INTO 一律拒绝
- 禁止危险函数（SLEEP、BENCHMARK、LOAD_FILE、GET_LOCK 等，防止拖垮数据库或读服务器文件）
- 禁止会话变量（@a、@@version）
- 所有表必须在白名单内，并且不能带其他库名（挡住 information_schema、mysql 等系统库）
- 没有 LIMIT 的查询自动补上行数上限，已有的 LIMIT 超过上限时压低到上限
- 返回的是语法树重新生成的 SQL，而不是原始字符串：注释里夹带的内容
  （例如 MySQL 会执行的 /*! ... */）经过重新生成就不存在了

检查结果分两种：通过（可能被改写，例如补了 LIMIT），或者被拒绝（附带原因）。
被拒绝的请求不会进入“修正”流程：修正的目的是让 SQL 能跑，而对一条 DELETE 来说
正确的处理是拒绝，不是帮它改成别的样子。
"""

from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

MAX_ROWS = 1000

FORBIDDEN_NODES: tuple[type, ...] = tuple(
    t
    for t in (
        getattr(exp, name, None)
        for name in (
            "Insert",
            "Update",
            "Delete",
            "Drop",
            "Create",
            "Alter",
            "AlterTable",
            "TruncateTable",
            "Merge",
            "Command",
            "Set",
            "Use",
            "Into",
            "LoadData",
            "Grant",
            "Revoke",
            "Transaction",
            "Commit",
            "Rollback",
            "Kill",
            "Lock",
            "Parameter",
            "SessionParameter",
        )
    )
    if t is not None
)

FORBIDDEN_FUNCTIONS = {
    "sleep",
    "benchmark",
    "load_file",
    "get_lock",
    "release_lock",
    "is_free_lock",
    "master_pos_wait",
    "sys_exec",
    "sys_eval",
    "pg_sleep",
}


@dataclass
class GuardResult:
    ok: bool
    sql: str = ""  # 通过时是语法树重新生成的 SQL（可能已补 LIMIT）
    reason: str = ""  # 被拒绝时的原因
    rewrites: list[str] = field(default_factory=list)  # 做过哪些自动改写


def reject(reason: str) -> GuardResult:
    return GuardResult(ok=False, reason=reason)


def check_sql(
    sql: str, allowed_tables: set[str], max_rows: int = MAX_ROWS
) -> GuardResult:
    allowed = {t.lower() for t in allowed_tables}

    try:
        statements = [s for s in sqlglot.parse(sql, read="mysql") if s is not None]
    except SqlglotError as e:
        return reject(f"无法解析为 SQL：{str(e)[:120]}")
    if len(statements) != 1:
        return reject(f"只允许单条查询语句，实际有 {len(statements)} 条")

    tree = statements[0]
    if not isinstance(tree, exp.Query):
        return reject(f"只允许查询语句，不允许 {type(tree).__name__}")

    for node in tree.walk():
        if isinstance(node, FORBIDDEN_NODES):
            return reject(f"包含不允许的操作：{type(node).__name__}")
        if isinstance(node, (exp.Func, exp.Anonymous)):
            name = (
                node.name if isinstance(node, exp.Anonymous) else node.sql_name()
            ).lower()
            if name in FORBIDDEN_FUNCTIONS:
                return reject(f"包含不允许的函数：{name.upper()}")

    cte_names = {cte.alias.lower() for cte in tree.find_all(exp.CTE) if cte.alias}
    for table in tree.find_all(exp.Table):
        name = (table.name or "").lower()
        if not name:
            return reject("包含无法识别的表引用")
        if table.args.get("db") or table.args.get("catalog"):
            return reject(f"不允许访问其他库或系统库：{table.sql(dialect='mysql')}")
        if name not in allowed and name not in cte_names:
            return reject(f"访问了不在白名单内的表：{table.name}")

    rewrites: list[str] = []
    if isinstance(tree, exp.Select):
        limit = tree.args.get("limit")
        if limit is None:
            tree = tree.limit(max_rows)
            rewrites.append(f"补充 LIMIT {max_rows}")
        else:
            expr = limit.args.get("expression")
            if (
                isinstance(expr, exp.Literal)
                and expr.is_int
                and int(expr.name) > max_rows
            ):
                tree = tree.limit(max_rows)
                rewrites.append(f"LIMIT 压低到 {max_rows}")
    else:
        # UNION 等集合运算：外面包一层再限制行数
        tree = sqlglot.select("*").from_(tree.subquery("t")).limit(max_rows)
        rewrites.append(f"外包一层并补充 LIMIT {max_rows}")

    # comments=False：丢弃所有注释，MySQL 会执行的 /*! ... */ 之类的内容不会被带到最终 SQL 里
    return GuardResult(
        ok=True, sql=tree.sql(dialect="mysql", comments=False), rewrites=rewrites
    )
