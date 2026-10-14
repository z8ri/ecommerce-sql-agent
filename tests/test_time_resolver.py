from datetime import date

from app.agent.time_resolver import cn_to_int, resolve_time_expressions

AS_OF = date(2025, 12, 31)  # 星期三


def resolve(q, as_of=AS_OF):
    return {r["expression"]: r for r in resolve_time_expressions(q, as_of)}


def test_last_quarter_carries_year():
    r = resolve("上季度的GMV是多少")["上季度"]
    assert r["calendar_fields"] == "year = 2025 AND quarter = 'Q3'"
    assert r["date_id_between"] == [20250701, 20250930]


def test_last_quarter_wraps_year():
    r = resolve("上季度", date(2025, 2, 10))["上季度"]
    assert r["calendar_fields"] == "year = 2024 AND quarter = 'Q4'"


def test_this_quarter_and_this_month():
    assert resolve("本季度订单")["本季度"]["date_id_between"] == [20251001, 20251231]
    assert resolve("本月GMV")["本月"]["calendar_fields"] == "year = 2025 AND month = 12"


def test_last_month_is_previous_calendar_month_not_current():
    r = resolve("上个月的GMV")["上个月"]
    assert r["calendar_fields"] == "year = 2025 AND month = 11"
    assert r["date_id_between"] == [20251101, 20251130]


def test_last_month_across_year_boundary():
    r = resolve("上个月", date(2026, 1, 15))["上个月"]
    assert r["calendar_fields"] == "year = 2025 AND month = 12"


def test_last_last_month_not_confused_with_last_month():
    got = resolve("上上个月的订单")
    assert "上上个月" in got and "上个月" not in got
    assert got["上上个月"]["calendar_fields"] == "year = 2025 AND month = 10"


def test_years():
    got = resolve("去年和今年对比")
    assert got["去年"]["calendar_fields"] == "year = 2024"
    assert got["今年"]["calendar_fields"] == "year = 2025"
    assert resolve("前年")["前年"]["calendar_fields"] == "year = 2023"


def test_recent_days_is_inclusive_of_as_of():
    r = resolve("最近7天的订单")["最近7天"]
    assert r["date_id_between"] == [20251225, 20251231]
    assert resolve("近三十天")["近三十天"]["date_id_between"] == [20251202, 20251231]


def test_recent_months():
    r = resolve("最近3个月")["最近3个月"]
    assert r["date_id_between"] == [20251001, 20251231]


def test_weeks():
    assert resolve("本周")["本周"]["date_id_between"] == [20251229, 20260104]
    assert resolve("上周")["上周"]["date_id_between"] == [20251222, 20251228]


def test_bare_quarter_and_month_default_to_as_of_year():
    assert (
        resolve("第二季度的GMV")["第二季度"]["calendar_fields"]
        == "year = 2025 AND quarter = 'Q2'"
    )
    assert (
        resolve("6月的订单数")["6月"]["calendar_fields"] == "year = 2025 AND month = 6"
    )


def test_explicit_year_is_left_alone():
    assert resolve("2025年第二季度的GMV") == {}
    assert resolve("2024年6月的订单数") == {}


def test_no_time_expression():
    assert resolve("各渠道的GMV是多少") == {}


def test_cn_numbers():
    assert [
        cn_to_int(x) for x in ["7", "七", "十", "十五", "二十", "三十", "二十三", "两"]
    ] == [7, 7, 10, 15, 20, 30, 23, 2]
