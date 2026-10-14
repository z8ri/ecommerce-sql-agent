"""
相对时间表达解析

“上季度”“本月”“最近 7 天”“第二季度”这类表达的含义取决于“今天”是哪天，大模型自己推算很容易错：
评测里它会把“上季度”写成 quarter = 'Q3' 却不限定年份，把两年的数据加在一起；
也会把“上个月”理解成数据截止日期所在的月份。

这里用确定性代码在数据截止日期（as_of）上算出每个时间表达的日期范围，
作为“已确定的事实”交给 SQL 生成节点，大模型只负责把它翻译成 SQL，不再参与推算。
"""

import re
from calendar import monthrange
from datetime import date, timedelta

CN_DIGITS = {
    "零": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}

# 注入到 SQL 生成/修正提示词的规则，由 agent.resolve_time 开关控制是否启用
TIME_RULES = (
    "时间规则：时间信息中的 resolved 列出了问题里的相对时间表达（如上季度、本月、最近7天、"
    "未写年份的第二季度）经程序确定的含义和日期范围，必须直接采用，禁止自行重新推算。"
    "数据覆盖多个年份，按季度、月份筛选时必须同时限定年份。"
)


def cn_to_int(text: str) -> int | None:
    """支持阿拉伯数字，以及一到九十九的中文数字"""
    if text.isdigit():
        return int(text)
    if text == "十":
        return 10
    if text.startswith("十") and len(text) == 2:
        return 10 + CN_DIGITS.get(text[1], 0)
    if text.endswith("十") and len(text) == 2:
        return CN_DIGITS.get(text[0], 0) * 10
    if len(text) == 3 and text[1] == "十":
        return CN_DIGITS.get(text[0], 0) * 10 + CN_DIGITS.get(text[2], 0)
    if len(text) == 1 and text in CN_DIGITS:
        return CN_DIGITS[text]
    return None


def add_months(d: date, months: int) -> date:
    index = d.year * 12 + (d.month - 1) + months
    year, month = divmod(index, 12)
    return date(year, month + 1, min(d.day, monthrange(year, month + 1)[1]))


def month_range(year: int, month: int) -> tuple[date, date]:
    return date(year, month, 1), date(year, month, monthrange(year, month)[1])


def quarter_range(year: int, quarter: int) -> tuple[date, date]:
    start = date(year, (quarter - 1) * 3 + 1, 1)
    return start, month_range(year, quarter * 3)[1]


def date_id(d: date) -> int:
    return d.year * 10000 + d.month * 100 + d.day


def entry(
    expression, meaning, start: date, end: date, calendar_fields: str = ""
) -> dict:
    item = {
        "expression": expression,
        "meaning": meaning,
        "date_range": f"{start.isoformat()} ~ {end.isoformat()}",
        "date_id_between": [date_id(start), date_id(end)],
    }
    if calendar_fields:
        item["calendar_fields"] = calendar_fields
    return item


def month_entry(expression: str, meaning_prefix: str, year: int, month: int) -> dict:
    start, end = month_range(year, month)
    return entry(
        expression,
        f"{meaning_prefix}{year}年{month}月",
        start,
        end,
        f"year = {year} AND month = {month}",
    )


def quarter_entry(
    expression: str, meaning_prefix: str, year: int, quarter: int
) -> dict:
    start, end = quarter_range(year, quarter)
    return entry(
        expression,
        f"{meaning_prefix}{year}年第{quarter}季度",
        start,
        end,
        f"year = {year} AND quarter = 'Q{quarter}'",
    )


def year_entry(expression: str, year: int) -> dict:
    return entry(
        expression, f"{year}年", date(year, 1, 1), date(year, 12, 31), f"year = {year}"
    )


# 按“较长的表达优先”排列，扫描时不会把“上上个月”误认成“上个月”
PATTERNS = [
    ("last_last_month", r"上上个月|上上月"),
    ("last_month", r"上个月|上月"),
    ("this_month_to_date", r"本月至今|月初至今"),
    ("this_month", r"本月|这个月|当月"),
    ("last_quarter", r"上个季度|上季度|上一季度"),
    ("this_quarter", r"本季度|这个季度|当季"),
    ("ytd", r"年初至今|今年以来|本年迄今"),
    ("year_before_last", r"前年"),
    ("last_year", r"去年|上一年|上年"),
    ("this_year", r"今年|本年度|本年"),
    ("last_week", r"上周|上个星期|上星期"),
    ("this_week", r"本周|这周|这个星期|本星期"),
    ("day_before_yesterday", r"前天"),
    ("yesterday", r"昨天|昨日"),
    ("today", r"今天|今日"),
    ("recent_days", r"(?:最近|近|过去)([一二两三四五六七八九十\d]+)天"),
    (
        "recent_weeks",
        r"(?:最近|近|过去)([一二两三四五六七八九十\d]+)(?:个)?(?:周|星期)",
    ),
    ("recent_months", r"(?:最近|近|过去)([一二两三四五六七八九十\d]+)个?月"),
    ("bare_quarter", r"第([一二三四1-4])季度"),
    ("bare_month", r"(\d{1,2})月(?:份)?"),
]
SCANNER = re.compile("|".join(f"(?P<{name}>{pat})" for name, pat in PATTERNS))


def resolve_time_expressions(query: str, as_of: date) -> list[dict]:
    """找出问题里的相对时间表达，并基于数据截止日期 as_of 算出明确含义"""
    results: list[dict] = []
    seen: set[str] = set()

    def add(item: dict):
        if item["expression"] not in seen:
            seen.add(item["expression"])
            results.append(item)

    for m in SCANNER.finditer(query):
        kind = m.lastgroup
        text = m.group(0)
        # 嵌套在 (?P<name>(...)) 里的数字分组：取该命名分组后的第一个捕获组
        number_text = next(
            (g for g in m.groups()[PATTERNS_INDEX[kind] + 1 :] if g), None
        )
        before = query[: m.start()]

        if kind == "last_last_month":
            d = add_months(as_of.replace(day=1), -2)
            add(month_entry(text, "上上个月，即", d.year, d.month))
        elif kind == "last_month":
            d = add_months(as_of.replace(day=1), -1)
            add(month_entry(text, "上个月，即", d.year, d.month))
        elif kind == "this_month":
            add(month_entry(text, "本月，即", as_of.year, as_of.month))
        elif kind == "this_month_to_date":
            add(entry(text, "本月至今", as_of.replace(day=1), as_of))
        elif kind == "last_quarter":
            q = (as_of.month - 1) // 3 + 1
            year, q = (as_of.year, q - 1) if q > 1 else (as_of.year - 1, 4)
            add(quarter_entry(text, "上季度，即", year, q))
        elif kind == "this_quarter":
            add(
                quarter_entry(
                    text, "本季度，即", as_of.year, (as_of.month - 1) // 3 + 1
                )
            )
        elif kind == "ytd":
            add(entry(text, "今年年初至今", date(as_of.year, 1, 1), as_of))
        elif kind == "year_before_last":
            add(year_entry(text, as_of.year - 2))
        elif kind == "last_year":
            add(year_entry(text, as_of.year - 1))
        elif kind == "this_year":
            add(year_entry(text, as_of.year))
        elif kind in ("last_week", "this_week"):
            monday = as_of - timedelta(days=as_of.weekday())
            if kind == "last_week":
                monday -= timedelta(days=7)
            add(
                entry(
                    text,
                    "上周（周一至周日）"
                    if kind == "last_week"
                    else "本周（周一至周日）",
                    monday,
                    monday + timedelta(days=6),
                )
            )
        elif kind == "day_before_yesterday":
            d = as_of - timedelta(days=2)
            add(entry(text, "前天", d, d))
        elif kind == "yesterday":
            d = as_of - timedelta(days=1)
            add(entry(text, "昨天", d, d))
        elif kind == "today":
            add(entry(text, "今天（数据截止日期）", as_of, as_of))
        elif kind in ("recent_days", "recent_weeks", "recent_months"):
            n = cn_to_int(number_text or "")
            if not n:
                continue
            if kind == "recent_days":
                start = as_of - timedelta(days=n - 1)
            elif kind == "recent_weeks":
                start = as_of - timedelta(days=7 * n - 1)
            else:
                start = add_months(as_of, -n) + timedelta(days=1)
            add(
                entry(
                    text,
                    f"包含数据截止日期在内的最近 {n} {'天' if kind == 'recent_days' else '周' if kind == 'recent_weeks' else '个月'}",
                    start,
                    as_of,
                )
            )
        elif kind == "bare_quarter":
            if re.search(r"\d{4}年$", before):
                continue  # 已经写明年份，不需要补
            q = cn_to_int(number_text or "")
            if q and 1 <= q <= 4:
                add(quarter_entry(text, "未写年份，按数据截止年份，即", as_of.year, q))
        elif kind == "bare_month":
            if re.search(r"\d{4}年$", before):
                continue
            mth = int(number_text)
            if 1 <= mth <= 12:
                add(month_entry(text, "未写年份，按数据截止年份，即", as_of.year, mth))
    return results


# 每个命名分组在 m.groups() 里的位置，用来取出它内部的数字捕获组
PATTERNS_INDEX: dict[str, int] = {}
_idx = 0
for _name, _pat in PATTERNS:
    PATTERNS_INDEX[_name] = _idx
    _idx += 1 + re.compile(_pat).groups
