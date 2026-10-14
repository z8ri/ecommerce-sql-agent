"""评测报告

基于 eval/runs/<name>.json 里的原始记录和评测集标注计算各项指标，输出 Markdown。
指标定义都在这个文件里，改口径不需要重新调用大模型。

用法：
    uv run python -m eval.report baseline
    uv run python -m eval.report baseline baseline_r2  # 并排对比几次具体运行
    uv run python -m eval.report --groups baseline pin # 按组对比（每组自动收集 <tag>_r1..3），推荐
"""

import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

from eval.dataset import Question, load_questions

RUNS_DIR = Path(__file__).parent / "runs"


def load_run(name: str) -> list[dict]:
    return json.loads((RUNS_DIR / f"{name}.json").read_text(encoding="utf-8"))[
        "records"
    ]


def pct(x: float) -> str:
    return f"{x:.1%}"


def mean(xs):
    return sum(xs) / len(xs) if xs else None


def classify_failure(rec: dict, q: Question) -> str:
    """给失败题归因。顺序即优先级：先看有没有产出结果，再看是不是上游环节漏了信息"""
    reason = rec["reason"]
    if rec["pred_rows"] is None or reason.startswith("no_result"):
        return "执行失败（无结果）"
    if reason.startswith("row_count") and rec["n_pred_rows"] == 0:
        return "返回空结果"
    if q.gold_values and not set(q.gold_values) <= set(rec["retrieved_values"]):
        return "取值召回遗漏"
    if q.gold_metrics and not set(q.gold_metrics) <= set(rec["selected_metrics"]):
        return "指标选择错误"
    if q.gold_tables and not (
        {t for t in q.gold_tables if not t.startswith("dim_date")}
        <= set(rec["final_tables"])
    ):
        return "表选择遗漏"
    return "SQL逻辑/口径错误"


def stage_metrics(records: list[dict], qmap: dict[str, Question]) -> dict:
    out = {}
    value_qs = [(r, qmap[r["id"]]) for r in records if qmap[r["id"]].gold_values]
    metric_qs = [(r, qmap[r["id"]]) for r in records if qmap[r["id"]].gold_metrics]
    if value_qs:
        out["取值召回率（命中全部期望取值）"] = (
            mean(
                [set(q.gold_values) <= set(r["retrieved_values"]) for r, q in value_qs]
            ),
            len(value_qs),
        )
    if metric_qs:
        out["指标召回率（召回阶段）"] = (
            mean(
                [
                    set(q.gold_metrics) <= set(r["retrieved_metrics"])
                    for r, q in metric_qs
                ]
            ),
            len(metric_qs),
        )
        out["指标选择准确率（过滤后）"] = (
            mean(
                [
                    set(q.gold_metrics) <= set(r["selected_metrics"])
                    for r, q in metric_qs
                ]
            ),
            len(metric_qs),
        )

    # 表召回：忽略几乎所有题都会用到、且可以绕开的 dim_date
    def core(q):
        return {t for t in q.gold_tables if t != "dim_date"}

    table_qs = [(r, qmap[r["id"]]) for r in records if core(qmap[r["id"]])]
    out["表召回率（合并后）"] = (
        mean([core(q) <= set(r["merged_tables"]) for r, q in table_qs]),
        len(table_qs),
    )
    out["表召回率（过滤后）"] = (
        mean([core(q) <= set(r["final_tables"]) for r, q in table_qs]),
        len(table_qs),
    )
    return out


def summarize(records: list[dict], questions: list[Question]) -> dict:
    qmap = {q.id: q for q in questions}
    n = len(records)
    ex = [r["ex"] for r in records]
    summary = {
        "n": n,
        "ex": mean(ex),
        "executed": mean([r["pred_rows"] is not None for r in records]),
        "infra_errors": sum(1 for r in records if r.get("infra_error")),
        "retried": sum(1 for r in records if r.get("attempts", 1) > 1),
        "latency_p50": statistics.median(r["latency_s"] for r in records),
        "latency_p90": sorted(r["latency_s"] for r in records)[int(n * 0.9) - 1],
        "llm_calls": mean([r["llm_calls"] for r in records]),
        "tokens": mean([r["input_tokens"] + r["output_tokens"] for r in records]),
    }

    # 自纠错
    first_ok = [r for r in records if r["validate_error"] is None and r["first_sql"]]
    corrected = [r for r in records if r["corrected_sql"]]
    summary["first_pass_valid"] = len(first_ok) / n
    summary["corrected_n"] = len(corrected)
    summary["corrected_ex"] = mean([r["ex"] for r in corrected]) if corrected else None
    # 一次生成就通过语法校验的题里，仍然答错的比例：说明 EXPLAIN 校验抓不到语义错误
    summary["silent_wrong"] = (
        sum(1 for r in first_ok if not r["ex"]) / len(first_ok) if first_ok else None
    )

    # 分组
    by_diff, by_tag = defaultdict(list), defaultdict(list)
    for r in records:
        by_diff[r["difficulty"]].append(r["ex"])
        for t in r["tags"]:
            by_tag[t].append(r["ex"])
    summary["by_difficulty"] = {k: (mean(v), len(v)) for k, v in by_diff.items()}
    summary["by_tag"] = {k: (mean(v), len(v)) for k, v in by_tag.items()}

    # 失败归因
    causes = defaultdict(list)
    for r in records:
        if not r["ex"]:
            causes[classify_failure(r, qmap[r["id"]])].append(r["id"])
    summary["failure_causes"] = dict(causes)
    summary["stages"] = stage_metrics(records, qmap)
    return summary


def render(name: str, s: dict, records: list[dict], questions: list[Question]) -> str:
    qmap = {q.id: q for q in questions}
    L = [f"# 评测报告：{name}", ""]
    L += [
        "## 总览",
        "",
        "| 指标 | 数值 |",
        "|---|---|",
        f"| 题目数 | {s['n']} |",
        f"| **执行准确率 (EX)** | **{pct(s['ex'])}** |",
        f"| 产出结果的比例 | {pct(s['executed'])} |",
        f"| 首次生成即通过 EXPLAIN 校验 | {pct(s['first_pass_valid'])} |",
        f"| 其中答案仍然错误（校验抓不到的语义错误） | {pct(s['silent_wrong']) if s['silent_wrong'] is not None else '-'} |",
        f"| 触发修正的题数 / 修正后答对率 | {s['corrected_n']} / {pct(s['corrected_ex']) if s['corrected_ex'] is not None else '-'} |",
        f"| 延迟 P50 / P90 | {s['latency_p50']:.1f}s / {s['latency_p90']:.1f}s |",
        f"| 平均大模型调用次数 / 题 | {s['llm_calls']:.1f} |",
        f"| 平均 token / 题 | {s['tokens']:.0f} |",
        "",
        "## 分难度",
        "",
        "| 难度 | EX | 题数 |",
        "|---|---|---|",
    ]
    for k in ("easy", "medium", "hard"):
        if k in s["by_difficulty"]:
            v, c = s["by_difficulty"][k]
            L.append(f"| {k} | {pct(v)} | {c} |")
    L += ["", "## 分题型", "", "| 题型 | EX | 题数 |", "|---|---|---|"]
    for k, (v, c) in sorted(s["by_tag"].items(), key=lambda kv: kv[1][0]):
        L.append(f"| {k} | {pct(v)} | {c} |")
    L += ["", "## 各阶段指标", "", "| 阶段 | 数值 | 样本数 |", "|---|---|---|"]
    for k, (v, c) in s["stages"].items():
        L.append(f"| {k} | {pct(v)} | {c} |")
    L += ["", "## 失败归因", "", "| 原因 | 题数 | 题目 |", "|---|---|---|"]
    for k, ids in sorted(s["failure_causes"].items(), key=lambda kv: -len(kv[1])):
        L.append(f"| {k} | {len(ids)} | {', '.join(ids)} |")

    L += ["", "## 失败题明细", ""]
    for r in records:
        if r["ex"]:
            continue
        q = qmap[r["id"]]
        L += [
            f"### {r['id']} {r['question']}",
            f"- 归因：{classify_failure(r, q)}；判分：{r['reason']}",
            f"- Agent 结果预览：`{json.dumps(r['pred_rows'], ensure_ascii=False)[:200]}`",
            "- Agent SQL：",
            "```sql",
            (r["final_sql"] or "(无)").strip(),
            "```",
            "- 标准 SQL：",
            "```sql",
            q.gold_sql.strip(),
            "```",
            "",
        ]
    return "\n".join(L)


def render_stability(
    names: list[str], runs: list[list[dict]], summaries: list[dict]
) -> str:
    """同一配置多次运行的稳定性：均值、波动，以及每题的通过次数"""
    exs = [s["ex"] for s in summaries]
    mu = statistics.mean(exs)
    sd = statistics.stdev(exs) if len(exs) > 1 else 0.0
    passes = defaultdict(int)
    for run in runs:
        for r in run:
            passes[r["id"]] += int(r["ex"])
    k = len(runs)
    stable_pass = sorted(i for i, c in passes.items() if c == k)
    stable_fail = sorted(i for i, c in passes.items() if c == 0)
    flaky = sorted(i for i, c in passes.items() if 0 < c < k)
    return "\n".join(
        [
            f"## 稳定性（{k} 次运行：{', '.join(names)}）",
            "",
            f"- EX 均值 **{pct(mu)}**，标准差 {sd * 100:.1f} 个百分点，范围 {pct(min(exs))} ~ {pct(max(exs))}",
            f"- 每次都答对：{len(stable_pass)} 题；每次都答错：{len(stable_fail)} 题；时对时错（不稳定）：{len(flaky)} 题",
            f"- 稳定答错：{', '.join(stable_fail) or '-'}",
            f"- 不稳定：{', '.join(flaky) or '-'}",
            "",
        ]
    )


def render_compare(names: list[str], summaries: list[dict]) -> str:
    L = [
        "# 对比",
        "",
        "| 指标 | " + " | ".join(names) + " |",
        "|---|" + "---|" * len(names),
    ]

    def row(label, fn):
        L.append(f"| {label} | " + " | ".join(fn(s) for s in summaries) + " |")

    row("EX", lambda s: pct(s["ex"]))
    row("产出结果比例", lambda s: pct(s["executed"]))
    row("延迟 P50", lambda s: f"{s['latency_p50']:.1f}s")
    row("平均 LLM 调用", lambda s: f"{s['llm_calls']:.1f}")
    row("平均 token", lambda s: f"{s['tokens']:.0f}")
    tags = sorted({t for s in summaries for t in s["by_tag"]})
    for t in tags:
        row(
            f"EX · {t}",
            lambda s, t=t: pct(s["by_tag"][t][0]) if t in s["by_tag"] else "-",
        )
    return "\n".join(L)


def resolve_group(tag: str) -> list[str]:
    """tag=baseline -> baseline, baseline_r2, baseline_r3；tag=pin -> pin_r1, pin_r2, pin_r3"""
    files = list(RUNS_DIR.glob(f"{tag}.json")) + list(
        RUNS_DIR.glob(f"{tag}_r[0-9]*.json")
    )
    return sorted(f.stem for f in files)


def group_stats(tag: str, questions: list[Question]) -> dict:
    names = resolve_group(tag)
    if not names:
        sys.exit(f"找不到运行记录：{tag}")
    runs = [load_run(n) for n in names]
    sums = [summarize(r, questions) for r in runs]
    passes = defaultdict(int)
    for run in runs:
        for r in run:
            passes[r["id"]] += int(r["ex"])
    exs = [x["ex"] for x in sums]

    def avg(key):
        vals = [x[key] for x in sums if x[key] is not None]
        return mean(vals)

    tags = defaultdict(list)
    for x in sums:
        for t, (v, _) in x["by_tag"].items():
            tags[t].append(v)
    diffs = defaultdict(list)
    for x in sums:
        for t, (v, _) in x["by_difficulty"].items():
            diffs[t].append(v)
    return {
        "tag": tag,
        "n": len(runs),
        "ex_mean": statistics.mean(exs),
        "ex_sd": statistics.stdev(exs) if len(exs) > 1 else 0.0,
        "ex_min": min(exs),
        "ex_max": max(exs),
        "silent_wrong": avg("silent_wrong"),
        "infra_errors": avg("infra_errors"),
        "retried": avg("retried"),
        "latency_p50": avg("latency_p50"),
        "llm_calls": avg("llm_calls"),
        "tokens": avg("tokens"),
        "by_tag": {t: statistics.mean(v) for t, v in tags.items()},
        "by_difficulty": {t: statistics.mean(v) for t, v in diffs.items()},
        "passes": dict(passes),
    }


def render_groups(tags: list[str], questions: list[Question]) -> str:
    gs = [group_stats(t, questions) for t in tags]
    first, last = gs[0], gs[-1]
    head = ["指标"] + [f"{g['tag']} (n={g['n']})" for g in gs]
    if len(gs) > 1:
        head.append(f"Δ ({last['tag']} − {first['tag']})")
    L = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]

    def row(label, fn, delta=None):
        cells = [label] + [fn(g) for g in gs]
        if len(gs) > 1:
            cells.append(delta(first, last) if delta else "")
        L.append("| " + " | ".join(cells) + " |")

    row(
        "**EX 均值 ± 标准差**",
        lambda g: f"**{pct(g['ex_mean'])}** ± {g['ex_sd'] * 100:.1f}",
        lambda a, b: f"**{(b['ex_mean'] - a['ex_mean']) * 100:+.1f} 个百分点**",
    )
    row("EX 范围", lambda g: f"{pct(g['ex_min'])} ~ {pct(g['ex_max'])}")
    row(
        "校验抓不到的语义错误",
        lambda g: pct(g["silent_wrong"]) if g["silent_wrong"] is not None else "-",
    )
    row(
        "设施错误题数 / 重试题数（均值）",
        lambda g: f"{g['infra_errors']:.1f} / {g['retried']:.1f}",
    )
    row("延迟 P50", lambda g: f"{g['latency_p50']:.1f}s")
    row("平均 LLM 调用 / 题", lambda g: f"{g['llm_calls']:.1f}")
    row("平均 token / 题", lambda g: f"{g['tokens']:.0f}")
    for d in ("easy", "medium", "hard"):
        row(
            f"EX · {d}",
            lambda g, d=d: (
                pct(g["by_difficulty"][d]) if d in g["by_difficulty"] else "-"
            ),
            lambda a, b, d=d: (
                f"{(b['by_difficulty'][d] - a['by_difficulty'][d]) * 100:+.1f}"
            ),
        )
    all_tags = sorted({t for g in gs for t in g["by_tag"]})
    for t in all_tags:
        row(
            f"EX · {t}",
            lambda g, t=t: pct(g["by_tag"][t]) if t in g["by_tag"] else "-",
            lambda a, b, t=t: (
                f"{(b['by_tag'].get(t, 0) - a['by_tag'].get(t, 0)) * 100:+.1f}"
            ),
        )

    out = ["\n".join(L)]
    if len(gs) > 1:
        # 逐题变化：用通过率（通过次数 / 运行次数）比较，过滤掉单次运行的随机波动
        def rate(g, qid):
            return g["passes"].get(qid, 0) / g["n"]

        fixed = [q.id for q in questions if rate(last, q.id) - rate(first, q.id) >= 0.6]
        broke = [q.id for q in questions if rate(first, q.id) - rate(last, q.id) >= 0.6]
        still = [q.id for q in questions if rate(last, q.id) == 0]
        out += [
            "",
            f"- 明显变好的题（通过率提升 ≥ 60%）：{len(fixed)} 题 — {', '.join(fixed) or '-'}",
            f"- 明显变差的题（通过率下降 ≥ 60%）：{len(broke)} 题 — {', '.join(broke) or '-'}",
            f"- {last['tag']} 中仍然稳定答错：{len(still)} 题 — {', '.join(still) or '-'}",
        ]
    return "\n".join(out)


if __name__ == "__main__":
    if sys.argv[1:2] == ["--groups"]:
        print(render_groups(sys.argv[2:], load_questions()))
        sys.exit(0)
    names = sys.argv[1:]
    if not names:
        sys.exit(__doc__)
    questions = load_questions()
    runs = [load_run(n) for n in names]
    summaries = [summarize(r, questions) for r in runs]
    if len(names) == 1:
        md = render(names[0], summaries[0], runs[0], questions)
        (RUNS_DIR / f"{names[0]}.md").write_text(md, encoding="utf-8")
        print(md)
    else:
        print(render_compare(names, summaries))
        print()
        print(render_stability(names, runs, summaries))
