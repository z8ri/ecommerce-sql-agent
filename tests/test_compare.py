from decimal import Decimal

from eval.compare import compare


def c(gold, pred_cols, pred, **kw):
    return compare(gold, pred_cols, pred, **kw)


def test_exact_scalar():
    assert c([(15199933.82,)], ["GMV"], [(15199933.82,)]).ok


def test_decimal_vs_float_and_small_error():
    assert c([(Decimal("100.00"),)], ["x"], [(100.05,)]).ok
    assert not c([(100.0,)], ["x"], [(101.0,)]).ok


def test_extra_columns_and_reordered_columns():
    gold = [("华东", 10), ("华南", 20)]
    pred = [(10, "华东", 99), (20, "华南", 98)]
    assert c(gold, ["n", "region", "z"], pred).ok


def test_row_order_ignored_unless_ordered():
    gold = [("a", 1), ("b", 2)]
    pred = [("b", 2), ("a", 1)]
    assert c(gold, ["k", "v"], pred).ok
    assert not c(gold, ["k", "v"], pred, ordered=True).ok


def test_wrong_value_in_one_row_fails():
    gold = [("a", 1), ("b", 2)]
    pred = [("a", 1), ("b", 3)]
    assert not c(gold, ["k", "v"], pred).ok


def test_columns_swapped_between_rows_is_not_a_match():
    # 每列单独看取值集合都对，但行内配对是错的
    gold = [("a", 1), ("b", 2)]
    pred = [("a", 2), ("b", 1)]
    assert not c(gold, ["k", "v"], pred).ok


def test_row_count_mismatch():
    assert not c([(1,), (2,)], ["x"], [(1,)]).ok


def test_rate_rounded_to_four_decimals():
    assert c([(0.019349,)], ["rate"], [(0.0194,)]).ok


def test_percent_requires_flag():
    assert not c([(0.0431,)], ["r"], [(4.31,)]).ok
    assert c([(0.0431,)], ["r"], [(4.31,)], percent_ok=True).ok
    assert c([(4.31,)], ["r"], [(0.0431,)], percent_ok=True).ok


def test_null_handling():
    assert c([(None,)], ["x"], [(None,)]).ok
    assert not c([(None,)], ["x"], [(0,)]).ok


def test_numeric_string_equals_number():
    assert c([(6,)], ["month"], [("6",)]).ok


def test_empty_results():
    assert c([], ["x"], []).ok
    assert not c([], ["x"], [(1,)]).ok
