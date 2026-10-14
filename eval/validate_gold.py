"""校验评测集的标准 SQL

标准答案不可靠，后面的分数就没有意义。这里逐题检查：
- SQL 能在数仓上执行
- 结果非空，且不是全 NULL
- 带 LIMIT N 的排名题，第 N 名和第 N+1 名不并列（否则答案不唯一）

用法：uv run python -m eval.validate_gold
"""

import asyncio
import re
import sys

from sqlalchemy import text

from app.clients.mysql_client_manager import dw_mysql_client_manager
from app.repositories.mysql.dw.dw_mysql_repository import to_jsonable
from eval.dataset import load_questions


async def main() -> int:
    dw_mysql_client_manager.init()
    problems = 0
    questions = load_questions()
    async with dw_mysql_client_manager.session_factory() as session:
        for q in questions:
            try:
                result = await session.execute(text(q.gold_sql))
                rows = [tuple(to_jsonable(v) for v in r) for r in result.fetchall()]
            except Exception as e:
                print(f"[FAIL] {q.id} 执行出错: {str(e)[:160]}")
                problems += 1
                continue

            issues = []
            if not rows:
                issues.append("结果为空")
            elif all(v is None for r in rows for v in r):
                issues.append("结果全为 NULL")

            # 排名题：检查第 N 名与第 N+1 名是否并列
            m = re.search(r"LIMIT\s+(\d+)\s*$", q.gold_sql.strip(), re.I)
            if m and q.ordered and not issues:
                n = int(m.group(1))
                order_expr = re.search(
                    r"ORDER BY\s+(.+?)\s+(?:DESC|ASC)?\s+LIMIT", q.gold_sql, re.I | re.S
                )
                if order_expr and n >= 1:
                    probe = re.sub(
                        r"LIMIT\s+\d+\s*$",
                        f"LIMIT {n + 1}",
                        q.gold_sql.strip(),
                        flags=re.I,
                    )
                    # 把 SELECT 列表替换成排序表达式，直接比较第 N / N+1 名的排序值
                    probe_sql = re.sub(
                        r"^\s*SELECT\s+.+?\s+FROM\b",
                        f"SELECT {order_expr.group(1)} AS _k FROM",
                        probe,
                        count=1,
                        flags=re.I | re.S,
                    )
                    try:
                        ks = [
                            to_jsonable(r[0])
                            for r in (await session.execute(text(probe_sql))).fetchall()
                        ]
                        if len(ks) > n and ks[n - 1] == ks[n]:
                            issues.append(f"第 {n} 名与第 {n + 1} 名并列，答案不唯一")
                    except Exception:
                        pass  # 探测失败不影响题目本身

            status = "OK  " if not issues else "WARN"
            if issues:
                problems += 1
            preview = rows[0] if rows else ()
            print(
                f"[{status}] {q.id} rows={len(rows):<3} tables={sorted(q.gold_tables)} "
                f"first={str(preview)[:70]} {'; '.join(issues)}"
            )
    await dw_mysql_client_manager.close()
    print(f"\n共 {len(questions)} 题，{problems} 题需要处理")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
