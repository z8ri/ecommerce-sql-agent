"""
演示数仓数据生成脚本

用固定随机种子生成一份“多渠道电商”仿真数据并导入 dw 库，同一份代码在任何机器上
生成的数据完全一致，所以后面的评测集（问题 + 标准 SQL）可以稳定复现。

数据里刻意埋了一些真实业务里常见的特征，方便检验问数 Agent 是否真的理解口径：
- 大促（618 / 双11 / 双12）、春节、周末带来的销量波动，以及整体增长趋势
- 订单有 已完成 / 已取消 / 已退款 三种状态，GMV 等指标需要排除已取消订单
- 退款单独成表，退款原因、退款率随品类变化
- 流量与订单分属不同事实表，转化率需要跨事实表计算
- 地区、店铺、品类等字段取值用全称（如“广东省”），用户通常只说“广东”

用法：uv run python -m app.scripts.seed_dw
"""

import asyncio
import bisect
import math
import random
import re
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import text

from app.clients.mysql_client_manager import dw_mysql_client_manager
from app.core.log import logger

SEED = 20260101
START = date(2024, 1, 1)
END = date(2025, 12, 31)
# 维度表多生成一段日期，覆盖年底订单的发货和退款日期
DIM_DATE_END = date(2026, 1, 31)
CUSTOMER_COUNT = 12000

# (省份, 城市, 大区, 城市线级)
REGIONS = [
    ("上海市", "上海市", "华东", "一线"),
    ("江苏省", "南京市", "华东", "新一线"),
    ("江苏省", "苏州市", "华东", "新一线"),
    ("浙江省", "杭州市", "华东", "新一线"),
    ("浙江省", "宁波市", "华东", "新一线"),
    ("浙江省", "温州市", "华东", "二线"),
    ("山东省", "济南市", "华东", "二线"),
    ("山东省", "青岛市", "华东", "新一线"),
    ("安徽省", "合肥市", "华东", "新一线"),
    ("福建省", "厦门市", "华东", "二线"),
    ("北京市", "北京市", "华北", "一线"),
    ("天津市", "天津市", "华北", "新一线"),
    ("河北省", "石家庄市", "华北", "二线"),
    ("山西省", "太原市", "华北", "二线"),
    ("内蒙古自治区", "呼和浩特市", "华北", "三线及以下"),
    ("广东省", "广州市", "华南", "一线"),
    ("广东省", "深圳市", "华南", "一线"),
    ("广东省", "东莞市", "华南", "新一线"),
    ("广东省", "佛山市", "华南", "二线"),
    ("广西壮族自治区", "南宁市", "华南", "二线"),
    ("海南省", "海口市", "华南", "三线及以下"),
    ("湖北省", "武汉市", "华中", "新一线"),
    ("湖南省", "长沙市", "华中", "新一线"),
    ("河南省", "郑州市", "华中", "新一线"),
    ("河南省", "洛阳市", "华中", "三线及以下"),
    ("江西省", "南昌市", "华中", "二线"),
    ("四川省", "成都市", "西南", "新一线"),
    ("重庆市", "重庆市", "西南", "新一线"),
    ("云南省", "昆明市", "西南", "二线"),
    ("贵州省", "贵阳市", "西南", "二线"),
    ("陕西省", "西安市", "西北", "新一线"),
    ("甘肃省", "兰州市", "西北", "三线及以下"),
    ("新疆维吾尔自治区", "乌鲁木齐市", "西北", "三线及以下"),
    ("宁夏回族自治区", "银川市", "西北", "三线及以下"),
    ("辽宁省", "沈阳市", "东北", "新一线"),
    ("辽宁省", "大连市", "东北", "二线"),
    ("吉林省", "长春市", "东北", "二线"),
    ("黑龙江省", "哈尔滨市", "东北", "二线"),
]
TIER_WEIGHT = {"一线": 5.0, "新一线": 3.0, "二线": 1.5, "三线及以下": 0.8}
# 偏远大区的物流更慢
FAR_REGION_EXTRA_DAYS = {"西北": 1.0, "东北": 0.6, "西南": 0.5}

# 一级品类 -> 二级品类 -> (品牌列表, 价格区间)
CATALOG = {
    "手机数码": {
        "手机": (["苹果", "华为", "小米", "OPPO"], (1999, 9999)),
        "耳机音频": (["索尼", "漫步者", "华为", "小米"], (99, 1999)),
        "智能穿戴": (["华为", "小米", "苹果"], (199, 3299)),
        "电脑平板": (["联想", "苹果", "华为"], (2999, 12999)),
    },
    "家用电器": {
        "厨房电器": (["美的", "苏泊尔", "九阳"], (89, 1299)),
        "大家电": (["海尔", "美的", "格力"], (1999, 8999)),
        "生活电器": (["戴森", "小米", "飞利浦"], (199, 3999)),
    },
    "美妆护肤": {
        "面部护肤": (["欧莱雅", "雅诗兰黛", "珀莱雅"], (99, 1299)),
        "彩妆": (["完美日记", "花西子", "MAC"], (59, 499)),
        "洗护": (["海飞丝", "舒肤佳", "滋源"], (19, 159)),
    },
    "服饰鞋包": {
        "男装": (["优衣库", "太平鸟", "七匹狼"], (79, 699)),
        "女装": (["ZARA", "UR", "韩都衣舍"], (89, 899)),
        "运动鞋": (["耐克", "阿迪达斯", "安踏"], (199, 1299)),
        "箱包": (["新秀丽", "小米", "蔻驰"], (99, 2999)),
    },
    "食品生鲜": {
        "休闲零食": (["三只松鼠", "良品铺子", "百草味"], (9, 129)),
        "水果生鲜": (["佳沛", "都乐", "本来生活"], (19, 199)),
        "粮油调味": (["金龙鱼", "海天", "鲁花"], (9, 189)),
        "饮料冲调": (["农夫山泉", "元气森林", "雀巢"], (5, 99)),
    },
    "母婴用品": {
        "奶粉": (["飞鹤", "爱他美", "惠氏"], (199, 599)),
        "纸尿裤": (["帮宝适", "花王", "好奇"], (59, 299)),
        "玩具": (["乐高", "奥迪双钻", "费雪"], (39, 999)),
    },
    "运动户外": {
        "健身器材": (["Keep", "迪卡侬", "亿健"], (49, 2999)),
        "户外装备": (["北面", "哥伦比亚", "探路者"], (99, 1999)),
    },
    "家居日用": {
        "家纺": (["罗莱", "水星", "富安娜"], (89, 1299)),
        "收纳清洁": (["宜家", "妙洁", "乐扣乐扣"], (9, 299)),
    },
}
CATEGORY_SHORT = {
    "手机数码": "数码",
    "家用电器": "家电",
    "美妆护肤": "美妆",
    "服饰鞋包": "服饰",
    "食品生鲜": "生鲜",
    "母婴用品": "母婴",
    "运动户外": "户外",
    "家居日用": "家居",
}
SHOP_PREFIXES = ["优选", "臻品", "爱购", "百汇", "星选", "悦享", "领航", "嘉禾"]
SHOP_TYPES = ["旗舰店", "专营店", "自营店"]
PRODUCT_VARIANTS = ["旗舰款", "标准款", "入门款", "限定款"]

# (渠道名, 渠道类型, 流量权重, 基础转化率, 取消率)
CHANNELS = [
    ("微信小程序", "自营渠道", 1.0, 0.045, 0.04),
    ("自营App", "自营渠道", 0.9, 0.050, 0.04),
    ("H5商城", "自营渠道", 0.6, 0.025, 0.06),
    ("天猫", "第三方平台", 1.5, 0.032, 0.05),
    ("京东", "第三方平台", 1.3, 0.035, 0.05),
    ("抖音直播", "内容电商", 1.6, 0.020, 0.09),
]

# (券名, 类型, 门槛, 面额)
COUPONS = [
    ("新人立减10元", "新人券", 0, 10),
    ("新人立减20元", "新人券", 99, 20),
    ("满100减10", "满减券", 100, 10),
    ("满200减25", "满减券", 200, 25),
    ("满500减70", "满减券", 500, 70),
    ("满1000减160", "满减券", 1000, 160),
    ("满3000减500", "满减券", 3000, 500),
    ("无门槛5元券", "无门槛券", 0, 5),
    ("无门槛15元券", "无门槛券", 0, 15),
    ("无门槛30元券", "无门槛券", 0, 30),
]

CARRIERS = [("顺丰", 30), ("京东物流", 20), ("中通", 20), ("圆通", 15), ("韵达", 15)]
AGE_GROUPS = [("18-24岁", 22), ("25-34岁", 38), ("35-44岁", 25), ("45岁以上", 15)]
WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
REFUND_RATE_BY_CATEGORY = {
    "服饰鞋包": 0.12,
    "美妆护肤": 0.05,
    "手机数码": 0.04,
}
DEFAULT_REFUND_RATE = 0.03
REFUND_REASONS = {
    "通用": [
        ("质量问题", 30),
        ("商品与描述不符", 25),
        ("不想要了", 25),
        ("物流太慢", 10),
        ("拍错或多拍", 10),
    ],
    "服饰鞋包": [
        ("尺码不合适", 40),
        ("质量问题", 20),
        ("商品与描述不符", 15),
        ("不想要了", 20),
        ("物流太慢", 5),
    ],
}


def date_id_of(d: date) -> int:
    return d.year * 10000 + d.month * 100 + d.day


def date_of(date_id: int) -> date:
    return date(date_id // 10000, date_id // 100 % 100, date_id % 100)


def event_of(d: date) -> tuple[str, float]:
    """返回当天的节假日/大促名称，以及对整体流量的放大系数"""
    spring = {
        2024: (date(2024, 2, 8), date(2024, 2, 17)),
        2025: (date(2025, 1, 26), date(2025, 2, 4)),
    }
    nianhuo = {
        2024: (date(2024, 1, 20), date(2024, 2, 7)),
        2025: (date(2025, 1, 10), date(2025, 1, 25)),
    }
    if d.year in spring and spring[d.year][0] <= d <= spring[d.year][1]:
        return "春节", 0.5
    if d.year in nianhuo and nianhuo[d.year][0] <= d <= nianhuo[d.year][1]:
        return "年货节", 1.15
    if d.month == 1 and d.day <= 3:
        return "元旦", 1.1
    if d.month == 6 and d.day <= 18:
        return "618大促", 1.2 + 1.6 * (d.day - 1) / 17
    if d.month == 10 and d.day <= 7:
        return "国庆", 1.2
    if d.month == 11 and d.day <= 11:
        return "双11大促", 1.3 + 2.7 * (d.day - 1) / 10
    if d.month == 12 and d.day == 12:
        return "双12大促", 1.8
    return "日常", 1.0


def category_event_factor(event: str, category: str) -> float:
    """不同品类在不同节点的额外波动"""
    if event in ("618大促", "双11大促"):
        return {"手机数码": 1.4, "家用电器": 1.4, "美妆护肤": 1.5}.get(category, 1.0)
    if event == "年货节":
        return 1.6 if category == "食品生鲜" else 1.0
    if event == "春节":
        return 0.6 if category == "食品生鲜" else 1.0
    return 1.0


def weighted_choice(rnd: random.Random, pairs: list[tuple]):
    total = sum(w for _, w in pairs)
    r = rnd.random() * total
    acc = 0.0
    for value, w in pairs:
        acc += w
        if r <= acc:
            return value
    return pairs[-1][0]


def stochastic_round(rnd: random.Random, x: float) -> int:
    base = math.floor(x)
    return base + (1 if rnd.random() < x - base else 0)


def build_dimensions(rnd: random.Random) -> dict:
    """生成除客户外的所有维度表"""
    # dim_date
    dim_date = []
    d = START
    while d <= DIM_DATE_END:
        event, _ = event_of(d)
        dim_date.append(
            {
                "date_id": date_id_of(d),
                "full_date": d,
                "year": d.year,
                "quarter": f"Q{(d.month - 1) // 3 + 1}",
                "month": d.month,
                "day": d.day,
                "weekday": WEEKDAYS[d.weekday()],
                "is_weekend": 1 if d.weekday() >= 5 else 0,
                "holiday_name": event,
            }
        )
        d += timedelta(days=1)

    # dim_region
    dim_region = [
        {
            "region_id": f"R{i + 1:02d}",
            "province": province,
            "city": city,
            "region_name": region_name,
            "city_tier": tier,
        }
        for i, (province, city, region_name, tier) in enumerate(REGIONS)
    ]

    # dim_channel / dim_coupon
    dim_channel = [
        {"channel_id": f"CH{i + 1:02d}", "channel_name": n, "channel_type": t}
        for i, (n, t, _, _, _) in enumerate(CHANNELS)
    ]
    dim_coupon = [
        {
            "coupon_id": f"CP{i + 1:02d}",
            "coupon_name": n,
            "coupon_type": t,
            "threshold_amount": thr,
            "face_value": face,
        }
        for i, (n, t, thr, face) in enumerate(COUPONS)
    ]

    # dim_shop：每个一级品类 3 家店，覆盖不同店铺类型
    big_city_regions = [r for r in dim_region if r["city_tier"] in ("一线", "新一线")]
    prefixes = SHOP_PREFIXES[:]
    rnd.shuffle(prefixes)
    dim_shop = []
    for cat_index, category in enumerate(CATALOG):
        for k, shop_type in enumerate(SHOP_TYPES):
            prefix = prefixes[(cat_index + k) % len(prefixes)]
            dim_shop.append(
                {
                    "shop_id": f"S{len(dim_shop) + 1:02d}",
                    "shop_name": f"{prefix}{CATEGORY_SHORT[category]}{shop_type}",
                    "shop_type": shop_type,
                    "main_category": category,
                    "region_id": rnd.choice(big_city_regions)["region_id"],
                }
            )

    # dim_product：同品类的商品轮流分配给该品类的 3 家店
    shops_by_category = defaultdict(list)
    for shop in dim_shop:
        shops_by_category[shop["main_category"]].append(shop["shop_id"])
    dim_product = []
    counters = defaultdict(int)
    for category, l2_map in CATALOG.items():
        for l2, (brands, (low, high)) in l2_map.items():
            for brand in brands:
                for variant in rnd.sample(PRODUCT_VARIANTS, rnd.randint(2, 3)):
                    shop_id = shops_by_category[category][
                        counters[category] % len(shops_by_category[category])
                    ]
                    counters[category] += 1
                    price = math.exp(rnd.uniform(math.log(low), math.log(high)))
                    price = round(price) if price > 50 else round(price, 1)
                    dim_product.append(
                        {
                            "product_id": f"P{len(dim_product) + 1:03d}",
                            "product_name": f"{brand}{l2}{variant}",
                            "category_l1": category,
                            "category_l2": l2,
                            "brand": brand,
                            "shop_id": shop_id,
                            "list_price": float(price),
                        }
                    )
    return {
        "dim_date": dim_date,
        "dim_region": dim_region,
        "dim_channel": dim_channel,
        "dim_coupon": dim_coupon,
        "dim_shop": dim_shop,
        "dim_product": dim_product,
    }


def build_customers(rnd: random.Random, dim_region: list[dict]) -> list[dict]:
    region_pairs = [(r, TIER_WEIGHT[r["city_tier"]]) for r in dim_region]
    channel_pairs = [(c[0], c[2]) for c in CHANNELS]
    customers = []
    for i in range(CUSTOMER_COUNT):
        if rnd.random() < 0.4:
            reg = date(2023, 6, 1) + timedelta(days=rnd.randint(0, 213))
        else:
            reg = START + timedelta(days=rnd.randint(0, (END - START).days))
        customers.append(
            {
                "customer_id": f"C{i + 1:05d}",
                "gender": "女" if rnd.random() < 0.55 else "男",
                "age_group": weighted_choice(rnd, AGE_GROUPS),
                "member_level": "普通会员",
                "register_date_id": date_id_of(reg),
                "register_channel": weighted_choice(rnd, channel_pairs),
                "region_id": weighted_choice(rnd, region_pairs)["region_id"],
                "_propensity": rnd.lognormvariate(0, 1.0),
            }
        )
    customers.sort(key=lambda c: c["register_date_id"])
    return customers


def build_facts(rnd: random.Random, dims: dict, customers: list[dict]) -> dict:
    """按天生成流量、订单、订单明细和退款"""
    region_by_id = {r["region_id"]: r for r in dims["dim_region"]}
    shop_region = {
        s["shop_id"]: region_by_id[s["region_id"]]["region_name"]
        for s in dims["dim_shop"]
    }
    shop_category = {s["shop_id"]: s["main_category"] for s in dims["dim_shop"]}
    products_by_shop = defaultdict(list)
    for p in dims["dim_product"]:
        products_by_shop[p["shop_id"]].append(p)
    product_weights = {
        shop_id: [1.0 / (rank + 1) ** 0.8 for rank in range(len(products))]
        for shop_id, products in products_by_shop.items()
    }

    # 每家店的体量，以及它入驻的 3 个渠道
    shop_pop = {s["shop_id"]: rnd.uniform(11, 38) for s in dims["dim_shop"]}
    shop_channels = {
        s["shop_id"]: rnd.sample(range(len(CHANNELS)), 3) for s in dims["dim_shop"]
    }
    channel_ids = [c["channel_id"] for c in dims["dim_channel"]]

    # 按注册时间排好序的客户前缀和，用来在“已注册客户”里按活跃度抽样
    reg_dates = [c["register_date_id"] for c in customers]
    prefix = [0.0]
    for c in customers:
        prefix.append(prefix[-1] + c["_propensity"])

    def pick_customer(date_id: int) -> dict:
        k = bisect.bisect_right(reg_dates, date_id)
        if rnd.random() < 0.2:
            return customers[rnd.randint(max(0, k - 300), k - 1)]
        u = rnd.random() * prefix[k]
        return customers[min(bisect.bisect_left(prefix, u, 1, k + 1) - 1, k - 1)]

    traffic, orders, items, refunds = [], [], [], []
    seen_customers: set[str] = set()
    refund_seq = 0
    total_days = (END - START).days
    coupons = dims["dim_coupon"]

    d = START
    while d <= END:
        date_id = date_id_of(d)
        event, event_factor = event_of(d)
        trend = 1.0 + 0.5 * (d - START).days / total_days
        weekend = 1.1 if d.weekday() >= 5 else 1.0
        big_event = event in ("618大促", "双11大促", "双12大促")
        order_seq = 0

        for shop in dims["dim_shop"]:
            shop_id = shop["shop_id"]
            category = shop_category[shop_id]
            cat_factor = category_event_factor(event, category)
            for channel_index in shop_channels[shop_id]:
                _, _, chan_weight, chan_conv, chan_cancel = CHANNELS[channel_index]
                visitors = max(
                    1,
                    int(
                        shop_pop[shop_id]
                        * chan_weight
                        * event_factor
                        * cat_factor
                        * trend
                        * weekend
                        * rnd.lognormvariate(0, 0.25)
                    ),
                )
                conv = (
                    chan_conv
                    * (1.25 if big_event else 1.0)
                    * rnd.lognormvariate(0, 0.15)
                )
                n_orders = min(stochastic_round(rnd, visitors * conv), visitors)
                traffic.append(
                    {
                        "date_id": date_id,
                        "shop_id": shop_id,
                        "channel_id": channel_ids[channel_index],
                        "visitors": visitors,
                        "page_views": int(visitors * rnd.uniform(2.5, 4.5)),
                        "cart_users": max(
                            n_orders, int(visitors * rnd.uniform(0.07, 0.14))
                        ),
                    }
                )

                for _ in range(n_orders):
                    order_seq += 1
                    order_id = f"ORD{date_id}{order_seq:06d}"
                    customer = pick_customer(date_id)
                    is_new = 0 if customer["customer_id"] in seen_customers else 1
                    seen_customers.add(customer["customer_id"])

                    # 订单明细
                    n_items = rnd.choice([1, 1, 1, 2, 2, 3])
                    shop_products = products_by_shop[shop_id]
                    picked = {}
                    for _ in range(n_items):
                        p = rnd.choices(shop_products, product_weights[shop_id])[0]
                        picked[p["product_id"]] = p
                    price_factor = 1.0
                    if big_event:
                        price_factor = rnd.uniform(0.80, 0.92)
                    elif event == "年货节":
                        price_factor = rnd.uniform(0.92, 0.97)
                    elif rnd.random() < 0.2:
                        price_factor = rnd.uniform(0.93, 0.99)
                    gross = 0.0
                    for n, p in enumerate(picked.values(), start=1):
                        qty = 1
                        if p["list_price"] < 100:
                            qty = rnd.choice([1, 1, 2, 3, 5])
                        elif p["list_price"] < 500:
                            qty = rnd.choice([1, 1, 1, 2])
                        unit_price = round(p["list_price"] * price_factor, 2)
                        amount = round(unit_price * qty, 2)
                        gross += amount
                        items.append(
                            {
                                "item_id": f"{order_id}-{n}",
                                "order_id": order_id,
                                "product_id": p["product_id"],
                                "quantity": qty,
                                "unit_price": unit_price,
                                "item_amount": amount,
                            }
                        )
                    gross = round(gross, 2)

                    # 优惠券
                    coupon_id, discount = None, 0.0
                    if rnd.random() < (0.5 if big_event else 0.3):
                        eligible = [
                            c
                            for c in coupons
                            if c["threshold_amount"] <= gross
                            and (c["coupon_type"] != "新人券" or is_new)
                        ]
                        if eligible:
                            eligible.sort(key=lambda c: c["face_value"], reverse=True)
                            c = rnd.choice(eligible[:2])
                            coupon_id = c["coupon_id"]
                            discount = float(min(c["face_value"], gross * 0.5))
                    shipping_fee = 0.0 if gross >= 99 else 8.0
                    pay = round(gross - discount + shipping_fee, 2)

                    # 订单状态
                    if rnd.random() < chan_cancel:
                        status = "已取消"
                    elif rnd.random() < REFUND_RATE_BY_CATEGORY.get(
                        category, DEFAULT_REFUND_RATE
                    ):
                        status = "已退款"
                    else:
                        status = "已完成"

                    carrier = ship_date_id = delivery_days = review = None
                    if status != "已取消":
                        carrier = weighted_choice(rnd, CARRIERS)
                        customer_region = region_by_id[customer["region_id"]][
                            "region_name"
                        ]
                        same_region = customer_region == shop_region[shop_id]
                        days = (1 if same_region else 2) + rnd.randint(0, 1)
                        if not same_region:
                            days += int(
                                rnd.random()
                                < FAR_REGION_EXTRA_DAYS.get(customer_region, 0.0)
                            )
                        if big_event and rnd.random() < 0.4:
                            days += 1
                        if carrier == "顺丰" and days > 1 and rnd.random() < 0.6:
                            days -= 1
                        delivery_days = days
                        ship_date_id = date_id_of(d + timedelta(days=rnd.randint(0, 2)))
                        if status == "已完成" and rnd.random() < 0.45:
                            late = max(0, days - 3)
                            probs = [
                                0.03 + 0.02 * late,
                                0.03 + 0.01 * late,
                                0.07,
                                0.20,
                                max(0.1, 0.62 - 0.06 * late),
                            ]
                            review = rnd.choices([1, 2, 3, 4, 5], probs)[0]

                    orders.append(
                        {
                            "order_id": order_id,
                            "customer_id": customer["customer_id"],
                            "shop_id": shop_id,
                            "channel_id": channel_ids[channel_index],
                            "region_id": customer["region_id"],
                            "date_id": date_id,
                            "coupon_id": coupon_id,
                            "order_status": status,
                            "gross_amount": gross,
                            "discount_amount": round(discount, 2),
                            "shipping_fee": shipping_fee,
                            "pay_amount": pay,
                            "item_count": len(picked),
                            "is_new_customer": is_new,
                            "carrier": carrier,
                            "ship_date_id": ship_date_id,
                            "delivery_days": delivery_days,
                            "review_score": review,
                        }
                    )

                    if status == "已退款":
                        refund_seq += 1
                        refund_day = min(
                            d + timedelta(days=rnd.randint(3, 20)), DIM_DATE_END
                        )
                        full = rnd.random() < 0.7
                        refund_amount = (
                            pay if full else round(pay * rnd.uniform(0.2, 0.8), 2)
                        )
                        reasons = REFUND_REASONS.get(category, REFUND_REASONS["通用"])
                        refunds.append(
                            {
                                "refund_id": f"RF{refund_seq:07d}",
                                "order_id": order_id,
                                "date_id": date_id_of(refund_day),
                                "refund_amount": refund_amount,
                                "refund_reason": weighted_choice(rnd, reasons),
                            }
                        )
        d += timedelta(days=1)

    return {
        "fact_traffic": traffic,
        "fact_order": orders,
        "fact_order_item": items,
        "fact_refund": refunds,
    }


def assign_member_levels(customers: list[dict], orders: list[dict]):
    """会员等级由实际有效订单数反推，保证维度表和事实表口径一致"""
    counts: dict[str, int] = defaultdict(int)
    for o in orders:
        if o["order_status"] != "已取消":
            counts[o["customer_id"]] += 1
    for c in customers:
        n = counts.get(c["customer_id"], 0)
        c["member_level"] = (
            "钻石会员"
            if n >= 12
            else "金牌会员"
            if n >= 7
            else "银牌会员"
            if n >= 3
            else "普通会员"
        )


def split_statements(sql_text: str) -> list[str]:
    sql_text = re.sub(r"--[^\n]*", "", sql_text)
    return [s.strip() for s in sql_text.split(";") if s.strip()]


async def load(tables: dict[str, list[dict]], ddl_path: Path):
    dw_mysql_client_manager.init()
    try:
        async with dw_mysql_client_manager.session_factory() as session:
            # 重建表结构：只执行建表相关语句，库和授权由 MySQL 容器初始化时负责
            for stmt in split_statements(ddl_path.read_text(encoding="utf-8")):
                if stmt.upper().startswith(("DROP TABLE", "CREATE TABLE")):
                    await session.execute(text(stmt))
            await session.commit()

            for name, rows in tables.items():
                if not rows:
                    continue
                columns = [c for c in rows[0] if not c.startswith("_")]
                sql = text(
                    f"INSERT INTO {name} ({', '.join(columns)}) "
                    f"VALUES ({', '.join(':' + c for c in columns)})"
                )
                for i in range(0, len(rows), 2000):
                    batch = [{c: r[c] for c in columns} for r in rows[i : i + 2000]]
                    await session.execute(sql, batch)
                await session.commit()
                logger.info(f"{name}: {len(rows)} 行")
    finally:
        await dw_mysql_client_manager.close()


def generate() -> dict[str, list[dict]]:
    rnd = random.Random(SEED)
    dims = build_dimensions(rnd)
    customers = build_customers(rnd, dims["dim_region"])
    facts = build_facts(rnd, dims, customers)
    assign_member_levels(customers, facts["fact_order"])
    # 客户表放在维度之后，保持与建表顺序一致
    return {**dims, "dim_customer": customers, **facts}


if __name__ == "__main__":
    ddl = Path(__file__).parents[2] / "docker" / "mysql" / "dw.sql"
    asyncio.run(load(generate(), ddl))
