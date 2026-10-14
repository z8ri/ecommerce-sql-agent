"""评测集加载

从 eval/dataset.yaml 读取题目，并用 sqlglot 从标准 SQL 里解析出涉及的表，
这样“标准答案用到了哪些表”不需要手工标注，也不会和 SQL 不一致。
"""

from dataclasses import dataclass, field
from pathlib import Path

import sqlglot
import yaml
from sqlglot import exp

DATASET_PATH = Path(__file__).parent / "dataset.yaml"


@dataclass
class Question:
    id: str
    question: str
    gold_sql: str
    tags: list[str] = field(default_factory=list)
    difficulty: str = "medium"
    ordered: bool = False
    percent_ok: bool = False
    gold_metrics: list[str] = field(default_factory=list)
    gold_values: list[str] = field(default_factory=list)

    @property
    def gold_tables(self) -> set[str]:
        return tables_of(self.gold_sql)


def tables_of(sql: str) -> set[str]:
    """解析 SQL 里引用的真实表名（不含 CTE / 子查询别名）"""
    tree = sqlglot.parse_one(sql, read="mysql")
    cte_names = {cte.alias for cte in tree.find_all(exp.CTE)}
    return {
        t.name for t in tree.find_all(exp.Table) if t.name and t.name not in cte_names
    }


def load_questions(path: Path = DATASET_PATH) -> list[Question]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    questions = [Question(**item) for item in data["questions"]]
    ids = [q.id for q in questions]
    if len(ids) != len(set(ids)):
        raise ValueError("评测集中存在重复的题目 id")
    return questions
