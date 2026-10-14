from app.agent.nodes.verify_result import rule_based_issues, summarize


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
