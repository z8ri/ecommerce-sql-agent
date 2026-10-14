"""评测运行器

直接驱动 LangGraph（不经过 HTTP），一边执行一边截取每个节点的输出：
关键词、召回的指标和取值、合并/过滤后的表、首次生成的 SQL、校验错误、修正后的 SQL，
再把最终 SQL 的执行结果和标准答案比对，得到每题的判分和各阶段的诊断信息。

原始记录写入 eval/runs/<name>.json，统计和报告由 eval/report.py 基于记录生成，
所以修改统计口径不需要重新调用大模型。

用法：
    uv run python -m eval.runner --name baseline
    uv run python -m eval.runner --name smoke --ids a01,b01,f01
    uv run python -m eval.runner --name quick --limit 10 --concurrency 4
"""

import argparse
import asyncio
import json
import time
from datetime import datetime
from pathlib import Path

from langchain_core.callbacks import BaseCallbackHandler
from sqlalchemy import text

from app.agent.context import DataAgentContext
from app.agent.graph import graph
from app.agent.state import DataAgentState
from app.clients.embedding_client_manager import embedding_client_manager
from app.clients.es_client_manager import es_client_manager
from app.clients.mysql_client_manager import (
    dw_mysql_client_manager,
    meta_mysql_client_manager,
)
from app.clients.qdrant_client_manager import qdrant_client_manager
from app.repositories.es.value_es_repository import ValueESRepository
from app.repositories.mysql.dw.dw_mysql_repository import DWMySQLRepository, to_jsonable
from app.repositories.mysql.meta.meta_mysql_repository import MetaMySQLRepository
from app.repositories.qdrant.column_qdrant_repository import ColumnQdrantRepository
from app.repositories.qdrant.metric_qdrant_repository import MetricQdrantRepository
from eval.compare import compare
from eval.dataset import Question, load_questions

RUNS_DIR = Path(__file__).parent / "runs"
QUESTION_TIMEOUT = 240
MAX_ATTEMPTS = 3
# 这些错误来自基础设施（连接超时、限流），不代表 Agent 答错；遇到时自动重试
TRANSIENT_ERRORS = (
    "ConnectionTimeout",
    "ResponseHandlingException",
    "TimeoutError",
    "ReadTimeout",
    "ConnectError",
    "RateLimit",
    "APIConnectionError",
    "APITimeoutError",
)


class LLMStats(BaseCallbackHandler):
    """统计一次问数调用了多少次大模型、消耗多少 token"""

    def __init__(self):
        self.calls = 0
        self.input_tokens = 0
        self.output_tokens = 0

    def on_chat_model_start(self, serialized, messages, **kwargs):
        self.calls += 1

    def on_llm_end(self, response, **kwargs):
        for generations in response.generations:
            for g in generations:
                usage = getattr(getattr(g, "message", None), "usage_metadata", None)
                if usage:
                    self.input_tokens += usage.get("input_tokens", 0)
                    self.output_tokens += usage.get("output_tokens", 0)


async def execute_gold(questions: list[Question]) -> dict[str, tuple[list, list]]:
    """执行所有标准 SQL，得到标准结果集 (列名, 行)"""
    gold = {}
    async with dw_mysql_client_manager.session_factory() as session:
        for q in questions:
            result = await session.execute(text(q.gold_sql))
            cols = list(result.keys())
            rows = [tuple(to_jsonable(v) for v in r) for r in result.fetchall()]
            gold[q.id] = (cols, rows)
    return gold


async def run_question(q: Question, gold: tuple[list, list]) -> dict:
    record = {
        "id": q.id,
        "question": q.question,
        "tags": q.tags,
        "difficulty": q.difficulty,
        "error": None,
        "keywords": [],
        "retrieved_metrics": [],
        "retrieved_values": [],
        "merged_tables": [],
        "final_tables": [],
        "final_columns": [],
        "selected_metrics": [],
        "first_sql": None,
        "validate_error": None,
        "corrected_sql": None,
        "final_sql": None,
        "pred_rows": None,
    }
    stats = LLMStats()
    started = time.time()

    async with (
        meta_mysql_client_manager.session_factory() as meta_session,
        dw_mysql_client_manager.session_factory() as dw_session,
    ):
        context = DataAgentContext(
            column_qdrant_repository=ColumnQdrantRepository(
                qdrant_client_manager.client
            ),
            embedding_client=embedding_client_manager.client,
            metric_qdrant_repository=MetricQdrantRepository(
                qdrant_client_manager.client
            ),
            value_es_repository=ValueESRepository(es_client_manager.client),
            meta_mysql_repository=MetaMySQLRepository(meta_session),
            dw_mysql_repository=DWMySQLRepository(dw_session),
        )
        try:
            async with asyncio.timeout(QUESTION_TIMEOUT):
                async for mode, chunk in graph.astream(
                    input=DataAgentState(query=q.question),
                    context=context,
                    stream_mode=["custom", "updates"],
                    config={"callbacks": [stats]},
                ):
                    if mode == "custom":
                        if chunk.get("type") == "result":
                            record["pred_rows"] = chunk["data"]
                        continue
                    for node, upd in chunk.items():
                        if not upd:
                            continue
                        capture(record, node, upd)
        except Exception as e:  # 节点异常 / 超时：记录下来，按失败处理
            record["error"] = f"{type(e).__name__}: {str(e)[:300]}"

    record["latency_s"] = round(time.time() - started, 2)
    record["llm_calls"] = stats.calls
    record["input_tokens"] = stats.input_tokens
    record["output_tokens"] = stats.output_tokens
    record["final_sql"] = record["corrected_sql"] or record["first_sql"]

    # 判分
    gold_cols, gold_rows = gold
    if record["pred_rows"] is None:
        record["ex"] = False
        record["reason"] = "no_result: " + (record["error"] or "未产出结果")
    else:
        pred_rows = record["pred_rows"]
        pred_cols = list(pred_rows[0].keys()) if pred_rows else []
        verdict = compare(
            gold_rows,
            pred_cols,
            [tuple(r.values()) for r in pred_rows],
            ordered=q.ordered,
            percent_ok=q.percent_ok,
        )
        record["ex"] = verdict.ok
        record["reason"] = verdict.reason
    record["n_pred_rows"] = len(record["pred_rows"] or [])
    record["pred_rows"] = (record["pred_rows"] or [])[:5]  # 只保留预览
    return record


async def run_with_retry(q: Question, gold: tuple[list, list]) -> dict:
    """基础设施类的瞬时错误重试；重试后仍失败的标记为 infra_error，报告里单独统计"""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        rec = await run_question(q, gold)
        rec["attempts"] = attempt
        transient = bool(rec["error"]) and any(
            k in rec["error"] for k in TRANSIENT_ERRORS
        )
        if transient and attempt < MAX_ATTEMPTS:
            await asyncio.sleep(3 * attempt)
            continue
        rec["infra_error"] = transient
        return rec


def capture(record: dict, node: str, upd: dict):
    """把节点输出里评测关心的部分记录下来"""
    if node == "extract_keywords":
        record["keywords"] = upd.get("keywords", [])
    elif node == "recall_metric":
        record["retrieved_metrics"] = [m.name for m in upd["retrieved_metric_infos"]]
    elif node == "recall_value":
        record["retrieved_values"] = [v.id for v in upd["retrieved_value_infos"]]
    elif node == "merge_retrieved_info":
        record["merged_tables"] = [t["name"] for t in upd["table_infos"]]
    elif node == "filter_table":
        record["final_tables"] = [t["name"] for t in upd["table_infos"]]
        record["final_columns"] = [
            f"{t['name']}.{c['name']}" for t in upd["table_infos"] for c in t["columns"]
        ]
    elif node == "pin_metric_columns":
        # 补回指标依赖字段之后的表上下文，才是 SQL 生成真正看到的
        record["final_tables"] = [t["name"] for t in upd["table_infos"]]
        record["final_columns"] = [
            f"{t['name']}.{c['name']}" for t in upd["table_infos"] for c in t["columns"]
        ]
    elif node == "filter_metric":
        record["selected_metrics"] = [m["name"] for m in upd["metric_infos"]]
    elif node == "generate_sql":
        record["first_sql"] = upd["sql"]
    elif node == "validate_sql":
        record["validate_error"] = upd.get("error")
    elif node == "correct_sql":
        record["corrected_sql"] = upd["sql"]


async def main(args):
    questions = load_questions()
    if args.ids:
        wanted = set(args.ids.split(","))
        questions = [q for q in questions if q.id in wanted]
    if args.limit:
        questions = questions[: args.limit]

    qdrant_client_manager.init()
    embedding_client_manager.init()
    es_client_manager.init()
    meta_mysql_client_manager.init()
    dw_mysql_client_manager.init()

    try:
        gold = await execute_gold(questions)
        sem = asyncio.Semaphore(args.concurrency)
        done = 0

        async def guarded(q):
            nonlocal done
            async with sem:
                rec = await run_with_retry(q, gold[q.id])
            done += 1
            mark = "PASS" if rec["ex"] else "FAIL"
            print(
                f"[{done}/{len(questions)}] {mark} {q.id} {rec['latency_s']}s "
                f"{rec['reason'][:70]}",
                flush=True,
            )
            return rec

        records = await asyncio.gather(*(guarded(q) for q in questions))
    finally:
        await qdrant_client_manager.close()
        await es_client_manager.close()
        await meta_mysql_client_manager.close()
        await dw_mysql_client_manager.close()

    RUNS_DIR.mkdir(exist_ok=True)
    out = RUNS_DIR / f"{args.name}.json"
    out.write_text(
        json.dumps(
            {
                "name": args.name,
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "records": records,
            },
            ensure_ascii=False,
            indent=1,
            default=str,
        ),
        encoding="utf-8",
    )
    infra = sum(r["infra_error"] for r in records)
    if infra:
        print(
            f"注意：{infra} 题因基础设施错误未能得到有效结果（已重试 {MAX_ATTEMPTS} 次）"
        )
    passed = sum(r["ex"] for r in records)
    print(f"\nEX = {passed}/{len(records)} = {passed / len(records):.1%}  -> {out}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True, help="本次运行的名字，也是结果文件名")
    parser.add_argument("--ids", help="只跑指定题目，逗号分隔")
    parser.add_argument("--limit", type=int, help="只跑前 N 题")
    parser.add_argument("--concurrency", type=int, default=4)
    asyncio.run(main(parser.parse_args()))
