from app.agent.nodes.verify_result import (
    drop_contradictions,
    rule_based_issues,
    strip_misleading_examples,
    summarize,
)


def test_empty_result_is_flagged():
    assert rule_based_issues([])


def test_all_null_single_row_is_flagged():
    assert rule_based_issues([{"gmv": None}])
    assert rule_based_issues([{"a": None, "b": None}])


def test_normal_results_pass_rules():
    assert rule_based_issues([{"gmv": 0}]) == []
    assert rule_based_issues([{"gmv": None}, {"gmv": 5}]) == []


def test_summary_truncates_rows():
    rows = [{"n": i} for i in range(50)]
    out = summarize(rows)
    assert "row_count: 50" in out
    assert "n: 9" in out and "n: 10" not in out


def test_contradictory_issues_are_dropped():
    issues = [
        "经逐项复核，无实质性错误，SQL 完全符合口径",
        "GMV 应使用 gross_amount 而不是 pay_amount",
        "指标口径计算正确，未发现问题",
    ]
    assert drop_contradictions(issues) == ["GMV 应使用 gross_amount 而不是 pay_amount"]


def test_numeric_examples_are_stripped_but_text_examples_kept():
    tables = [
        {
            "name": "fact_order",
            "columns": [
                {"name": "date_id", "type": "int", "examples": [20240101, 20240102]},
                {"name": "order_status", "type": "varchar(10)", "examples": ["已完成"]},
            ],
        }
    ]
    cols = strip_misleading_examples(tables)[0]["columns"]
    assert cols[0]["examples"] == [] and cols[1]["examples"] == ["已完成"]
    assert tables[0]["columns"][0]["examples"] == [20240101, 20240102]  # 不修改原对象
