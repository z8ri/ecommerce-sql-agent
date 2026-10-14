"""结果集比对（Execution Accuracy 的判分逻辑）

判断 Agent 生成的 SQL 执行结果和标准答案是否等价。原则是：只比较“答案”，不比较“写法”。

容忍：
- 列顺序、列别名不同（按列的取值内容去匹配，而不是按列名）
- Agent 多返回了额外的列（只要标准答案的每一列都能在结果里找到）
- 行顺序不同（题目没有要求排序时）
- 数值的小误差（相对 0.1%，比例类允许绝对 1e-4，因为模型常把比例四舍五入到 4 位小数）
- 比例类题目用百分数表示（0.0431 和 4.31 都算对，需要题目显式声明 percent_ok）

不容忍：
- 行数不一致、任意一个数值或文本取值不一致
"""

import math
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from itertools import product

REL_TOL = 1e-3
ABS_TOL = 1e-4
MAX_MAPPINGS = 500


@dataclass
class Verdict:
    ok: bool
    reason: str = ""


def norm(v):
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    if isinstance(v, str):
        return v.strip()
    return v


def is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def as_num(v):
    """数值，或者形如 '12' / '0.5' 的数字字符串；其他返回 None"""
    if is_num(v):
        return v
    if isinstance(v, str):
        try:
            return float(v)
        except ValueError:
            return None
    return None


def eq(a, b) -> bool:
    if a is None or b is None:
        return a is None and b is None
    na, nb = as_num(a), as_num(b)
    if na is not None and nb is not None:
        return math.isclose(na, nb, rel_tol=REL_TOL, abs_tol=ABS_TOL)
    return a == b


def sort_key(v):
    n = as_num(v)
    if v is None:
        return (2, 0, "")
    if n is not None:
        return (0, n, "")
    return (1, 0, str(v))


def column_matches(gcol: list, pcol: list) -> bool:
    if len(gcol) != len(pcol):
        return False
    return all(
        eq(a, b) for a, b in zip(sorted(gcol, key=sort_key), sorted(pcol, key=sort_key))
    )


def scaled(col: list, factor: float) -> list:
    return [v * factor if is_num(v) else v for v in col]


def row_eq(g: tuple, p: tuple) -> bool:
    return all(eq(a, b) for a, b in zip(g, p))


def rows_equal(grows: list[tuple], prows: list[tuple], ordered: bool) -> bool:
    if ordered:
        return all(row_eq(g, p) for g, p in zip(grows, prows))
    unused = list(range(len(prows)))
    for g in grows:
        for idx in unused:
            if row_eq(g, prows[idx]):
                unused.remove(idx)
                break
        else:
            return False
    return True


def compare(
    gold_rows: list,
    pred_cols: list[str],
    pred_rows: list,
    *,
    ordered: bool = False,
    percent_ok: bool = False,
) -> Verdict:
    """gold_rows / pred_rows 是按列顺序排好的行（列表或元组）"""
    gold_rows = [tuple(norm(v) for v in r) for r in gold_rows]
    pred_rows = [tuple(norm(v) for v in r) for r in pred_rows]

    if len(gold_rows) != len(pred_rows):
        return Verdict(False, f"row_count: gold={len(gold_rows)} pred={len(pred_rows)}")
    if not gold_rows:
        return Verdict(True)

    n_gold = len(gold_rows[0])
    gold_cols = [[r[j] for r in gold_rows] for j in range(n_gold)]
    pred_columns = [[r[k] for r in pred_rows] for k in range(len(pred_cols))]

    # 每个标准答案列，找出结果里内容一致的候选列（及需要的缩放倍数）
    candidates: list[list[tuple[int, float]]] = []
    for j, gcol in enumerate(gold_cols):
        found = []
        numeric = all(is_num(v) or v is None for v in gcol)
        for k, pcol in enumerate(pred_columns):
            if column_matches(gcol, pcol):
                found.append((k, 1.0))
            elif percent_ok and numeric:
                for factor in (100.0, 0.01):
                    if column_matches(gcol, scaled(pcol, factor)):
                        found.append((k, factor))
                        break
        if not found:
            return Verdict(
                False, f"missing_column: gold col {j} has no matching result column"
            )
        candidates.append(found)

    for tried, combo in enumerate(product(*candidates)):
        if tried >= MAX_MAPPINGS:
            break
        ks = [k for k, _ in combo]
        if len(set(ks)) != len(ks):
            continue
        projected = [
            tuple(
                (r[k] * factor if is_num(r[k]) and factor != 1.0 else r[k])
                for k, factor in combo
            )
            for r in pred_rows
        ]
        if rows_equal(gold_rows, projected, ordered):
            return Verdict(True)
    return Verdict(
        False, "row_mismatch: columns match individually but rows do not align"
    )
