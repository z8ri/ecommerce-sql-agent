# 评测报告：baseline

## 总览

| 指标 | 数值 |
|---|---|
| 题目数 | 92 |
| **执行准确率 (EX)** | **72.8%** |
| 产出结果的比例 | 100.0% |
| 首次生成即通过 EXPLAIN 校验 | 100.0% |
| 其中答案仍然错误（校验抓不到的语义错误） | 27.2% |
| 触发修正的题数 / 修正后答对率 | 0 / - |
| 延迟 P50 / P90 | 9.1s / 12.1s |
| 平均大模型调用次数 / 题 | 6.0 |
| 平均 token / 题 | 10160 |

## 分难度

| 难度 | EX | 题数 |
|---|---|---|
| easy | 100.0% | 32 |
| medium | 61.5% | 39 |
| hard | 52.4% | 21 |

## 分题型

| 题型 | EX | 题数 |
|---|---|---|
| relative_time | 16.7% | 6 |
| cross_fact | 33.3% | 9 |
| ratio | 61.5% | 26 |
| time | 65.9% | 41 |
| metric_caliber | 67.2% | 64 |
| multi_join | 69.2% | 13 |
| filter_value | 76.9% | 26 |
| ranking | 86.7% | 15 |
| simple_agg | 100.0% | 8 |

## 各阶段指标

| 阶段 | 数值 | 样本数 |
|---|---|---|
| 取值召回率（命中全部期望取值） | 92.3% | 26 |
| 指标召回率（召回阶段） | 100.0% | 67 |
| 指标选择准确率（过滤后） | 98.5% | 67 |
| 表召回率（合并后） | 100.0% | 92 |
| 表召回率（过滤后） | 88.0% | 92 |

## 失败归因

| 原因 | 题数 | 题目 |
|---|---|---|
| SQL逻辑/口径错误 | 17 | b10, c03, d03, d06, d07, d10, d11, d12, e02, e08, f08, f09, f11, g06, g10, h01, h02 |
| 表选择遗漏 | 7 | b04, b05, c14, e05, f05, f06, h03 |
| 指标选择错误 | 1 | g03 |

## 失败题明细

### b04 苹果品牌的销量是多少？
- 归因：表选择遗漏；判分：missing_column: gold col 0 has no matching result column
- Agent 结果预览：`[{"销量": 4998.0}]`
- Agent SQL：
```sql
SELECT SUM(foi.quantity) AS 销量
FROM fact_order_item foi
JOIN dim_product dp ON foi.product_id = dp.product_id
WHERE dp.brand = '苹果';
```
- 标准 SQL：
```sql
SELECT SUM(i.quantity) AS sales_qty
FROM fact_order_item i
JOIN fact_order o ON i.order_id = o.order_id
JOIN dim_product p ON i.product_id = p.product_id
WHERE p.brand = '苹果' AND o.order_status <> '已取消'
```

### b05 华为手机一共卖了多少钱？
- 归因：表选择遗漏；判分：missing_column: gold col 0 has no matching result column
- Agent 结果预览：`[{"销售额": 19683694.09}]`
- Agent SQL：
```sql
SELECT SUM(foi.item_amount) AS 销售额
FROM fact_order_item foi
JOIN dim_product dp ON foi.product_id = dp.product_id
WHERE dp.brand = '华为' AND dp.product_id IN (
    SELECT product_id FROM dim_product WHERE brand = '华为'
)
```
- 标准 SQL：
```sql
SELECT SUM(i.item_amount) AS sales_amount
FROM fact_order_item i
JOIN fact_order o ON i.order_id = o.order_id
JOIN dim_product p ON i.product_id = p.product_id
WHERE p.brand = '华为' AND p.category_l2 = '手机' AND o.order_status <> '已取消'
```

### b10 25-34岁客户的客单价是多少？
- 归因：SQL逻辑/口径错误；判分：missing_column: gold col 0 has no matching result column
- Agent 结果预览：`[{"客单价": 1437.270655}]`
- Agent SQL：
```sql
SELECT AVG(t2.pay_amount) AS 客单价
FROM dim_customer t1
INNER JOIN fact_order t2 ON t1.customer_id = t2.customer_id
WHERE t1.age_group = '25-34岁' AND t2.order_status != '已取消';
```
- 标准 SQL：
```sql
SELECT SUM(o.gross_amount) / COUNT(*) AS aov
FROM fact_order o JOIN dim_customer c ON o.customer_id = c.customer_id
WHERE c.age_group = '25-34岁' AND o.order_status <> '已取消'
```

### c03 2025年的客单价是多少？
- 归因：SQL逻辑/口径错误；判分：missing_column: gold col 0 has no matching result column
- Agent 结果预览：`[{"客单价": 1442.484342}]`
- Agent SQL：
```sql
SELECT SUM(t1.pay_amount) / COUNT(*) AS 客单价
FROM fact_order t1
JOIN dim_date t2 ON t1.date_id = t2.date_id
WHERE t2.year = 2025 AND t1.order_status != '已取消';
```
- 标准 SQL：
```sql
SELECT SUM(o.gross_amount) / COUNT(*) AS aov
FROM fact_order o JOIN dim_date d ON o.date_id = d.date_id
WHERE d.year = 2025 AND o.order_status <> '已取消'
```

### c14 2025年的净销售额是多少？
- 归因：表选择遗漏；判分：missing_column: gold col 0 has no matching result column
- Agent 结果预览：`[{"净销售额": 55782535.71}]`
- Agent SQL：
```sql
SELECT SUM(t1.pay_amount) - COALESCE(SUM(t2.refund_amount), 0) AS 净销售额
FROM fact_order t1
LEFT JOIN fact_refund t2 ON t1.date_id = t2.date_id AND t1.order_status IN ('已完成', '已退款')
INNER JOIN dim_date t3 ON t1.date_id = t3.date_id
WHERE t1.order_status != '已取消'
  AND t3.full_date >= '2025-01-01'
  AND t3.full_date <= '2025-12-31';
```
- 标准 SQL：
```sql
SELECT SUM(o.pay_amount) - COALESCE(SUM(r.refund_amount), 0) AS net_sales
FROM fact_order o
JOIN dim_date d ON o.date_id = d.date_id
LEFT JOIN fact_refund r ON r.order_id = o.order_id
WHERE d.year = 2025 AND o.order_status <> '已取消'
```

### d03 2025年双11大促期间的GMV是多少？
- 归因：SQL逻辑/口径错误；判分：missing_column: gold col 0 has no matching result column
- Agent 结果预览：`[{"GMV": 5227572.27}]`
- Agent SQL：
```sql
SELECT SUM(t1.pay_amount) AS GMV
FROM fact_order t1
JOIN dim_date t2 ON t1.date_id = t2.date_id
WHERE t2.holiday_name = '双11大促' AND t2.date_id >= 20250101 AND t2.date_id <= 20251231 AND t1.order_status != '已取消';
```
- 标准 SQL：
```sql
SELECT SUM(o.gross_amount) AS gmv
FROM fact_order o JOIN dim_date d ON o.date_id = d.date_id
WHERE d.year = 2025 AND d.holiday_name = '双11大促' AND o.order_status <> '已取消'
```

### d06 上个月的GMV是多少？
- 归因：SQL逻辑/口径错误；判分：missing_column: gold col 0 has no matching result column
- Agent 结果预览：`[{"GMV": 4405992.29}]`
- Agent SQL：
```sql
SELECT SUM(gross_amount) AS GMV FROM fact_order WHERE order_status != '已取消' AND date_id >= 20251201 AND date_id <= 20251231
```
- 标准 SQL：
```sql
SELECT SUM(o.gross_amount) AS gmv
FROM fact_order o JOIN dim_date d ON o.date_id = d.date_id
WHERE d.year = 2025 AND d.month = 11 AND o.order_status <> '已取消'
```

### d07 今年每个季度的GMV分别是多少？
- 归因：SQL逻辑/口径错误；判分：missing_column: gold col 1 has no matching result column
- Agent 结果预览：`[{"季度": "Q1", "GMV": 10167670.89}, {"季度": "Q2", "GMV": 14880244.49}, {"季度": "Q3", "GMV": 11363528.7}, {"季度": "Q4", "GMV": 16396465.18}]`
- Agent SQL：
```sql
SELECT 
  d.quarter AS 季度,
  SUM(f.pay_amount) AS GMV
FROM 
  fact_order f
JOIN 
  dim_date d ON f.date_id = d.date_id
WHERE 
  d.year = 2025
  AND f.order_status != '已取消'
GROUP BY 
  d.quarter
ORDER BY 
  d.quarter;
```
- 标准 SQL：
```sql
SELECT d.quarter, SUM(o.gross_amount) AS gmv
FROM fact_order o JOIN dim_date d ON o.date_id = d.date_id
WHERE d.year = 2025 AND o.order_status <> '已取消'
GROUP BY d.quarter ORDER BY d.quarter
```

### d10 2025年每个月的GMV是多少？
- 归因：SQL逻辑/口径错误；判分：missing_column: gold col 1 has no matching result column
- Agent 结果预览：`[{"年": 2025, "月": 1, "GMV": 3434531.25}, {"年": 2025, "月": 2, "GMV": 3218425.16}, {"年": 2025, "月": 3, "GMV": 3514714.48}, {"年": 2025, "月": 4, "GMV": 3452482.05}, {"年": 2025, "月": 5, "GMV": 3560191.72}]`
- Agent SQL：
```sql
SELECT 
  d.year AS 年,
  d.month AS 月,
  SUM(f.pay_amount) AS GMV
FROM fact_order f
JOIN dim_date d ON f.date_id = d.date_id
WHERE d.year = 2025 AND f.order_status != '已取消'
GROUP BY d.year, d.month
ORDER BY d.year, d.month;
```
- 标准 SQL：
```sql
SELECT d.month, SUM(o.gross_amount) AS gmv
FROM fact_order o JOIN dim_date d ON o.date_id = d.date_id
WHERE d.year = 2025 AND o.order_status <> '已取消'
GROUP BY d.month ORDER BY d.month
```

### d11 上季度的GMV是多少？
- 归因：SQL逻辑/口径错误；判分：missing_column: gold col 0 has no matching result column
- Agent 结果预览：`[{"GMV": 21029125.07}]`
- Agent SQL：
```sql
SELECT SUM(t1.gross_amount) AS GMV
FROM fact_order t1
JOIN dim_date t2 ON t1.date_id = t2.date_id
WHERE t2.quarter = 'Q3' AND t1.order_status != '已取消';
```
- 标准 SQL：
```sql
SELECT SUM(o.gross_amount) AS gmv
FROM fact_order o JOIN dim_date d ON o.date_id = d.date_id
WHERE d.year = 2025 AND d.quarter = 'Q3' AND o.order_status <> '已取消'
```

### d12 本季度有多少个有效订单？
- 归因：SQL逻辑/口径错误；判分：missing_column: gold col 0 has no matching result column
- Agent 结果预览：`[{"订单数": 20915}]`
- Agent SQL：
```sql
SELECT COUNT(DISTINCT fo.order_id) AS 订单数
FROM fact_order fo
JOIN dim_date dd ON fo.date_id = dd.date_id
WHERE fo.order_status != '已取消' AND dd.quarter = 'Q4';
```
- 标准 SQL：
```sql
SELECT COUNT(*) AS order_cnt
FROM fact_order o JOIN dim_date d ON o.date_id = d.date_id
WHERE d.year = 2025 AND d.quarter = 'Q4' AND o.order_status <> '已取消'
```

### e02 各渠道的GMV分别是多少，从高到低排列。
- 归因：SQL逻辑/口径错误；判分：missing_column: gold col 1 has no matching result column
- Agent 结果预览：`[{"渠道": "微信小程序", "GMV": 29543001.29}, {"渠道": "自营App", "GMV": 22494162.72}, {"渠道": "京东", "GMV": 14631698.16}, {"渠道": "天猫", "GMV": 13370972.07}, {"渠道": "抖音直播", "GMV": 9291548.0}]`
- Agent SQL：
```sql
SELECT 
  dc.channel_name AS 渠道,
  SUM(fo.pay_amount) AS GMV
FROM 
  fact_order fo
JOIN 
  dim_channel dc ON fo.channel_id = dc.channel_id
WHERE 
  fo.order_status != '已取消'
GROUP BY 
  dc.channel_name
ORDER BY 
  GMV DESC;
```
- 标准 SQL：
```sql
SELECT c.channel_name, SUM(o.gross_amount) AS gmv
FROM fact_order o JOIN dim_channel c ON o.channel_id = c.channel_id
WHERE o.order_status <> '已取消'
GROUP BY c.channel_name ORDER BY gmv DESC
```

### e05 各一级品类的销售额占比分别是多少？
- 归因：表选择遗漏；判分：missing_column: gold col 1 has no matching result column
- Agent 结果预览：`[{"一级品类": "手机数码", "销售额": 57553809.72, "销售额占比": 0.5616}, {"一级品类": "家用电器", "销售额": 17124328.77, "销售额占比": 0.1671}, {"一级品类": "服饰鞋包", "销售额": 7440124.42, "销售额占比": 0.0726}, {"一级品类": "运动户外", "销售额": 6863540.68,`
- Agent SQL：
```sql
SELECT 
  dp.category_l1 AS 一级品类,
  SUM(foi.item_amount) AS 销售额,
  ROUND(SUM(foi.item_amount) / SUM(SUM(foi.item_amount)) OVER(), 4) AS 销售额占比
FROM 
  dim_product dp
  INNER JOIN fact_order_item foi ON dp.product_id = foi.product_id
GROUP BY 
  dp.category_l1
ORDER BY 
  销售额 DESC;
```
- 标准 SQL：
```sql
SELECT p.category_l1, SUM(i.item_amount) / SUM(SUM(i.item_amount)) OVER () AS ratio
FROM fact_order_item i
JOIN fact_order o ON i.order_id = o.order_id
JOIN dim_product p ON i.product_id = p.product_id
WHERE o.order_status <> '已取消'
GROUP BY p.category_l1
```

### e08 各会员等级的客单价分别是多少？
- 归因：SQL逻辑/口径错误；判分：missing_column: gold col 1 has no matching result column
- Agent 结果预览：`[{"会员等级": "金牌会员", "客单价": 1409.236815}, {"会员等级": "银牌会员", "客单价": 1460.30189}, {"会员等级": "钻石会员", "客单价": 1441.092816}, {"会员等级": "普通会员", "客单价": 1419.970329}]`
- Agent SQL：
```sql
SELECT dc.member_level AS 会员等级, SUM(fo.pay_amount) / COUNT(*) AS 客单价
FROM fact_order fo
JOIN dim_customer dc ON fo.customer_id = dc.customer_id
WHERE fo.order_status != '已取消'
GROUP BY dc.member_level
```
- 标准 SQL：
```sql
SELECT c.member_level, SUM(o.gross_amount) / COUNT(*) AS aov
FROM fact_order o JOIN dim_customer c ON o.customer_id = c.customer_id
WHERE o.order_status <> '已取消'
GROUP BY c.member_level
```

### f05 2025年每个月的净销售额分别是多少？
- 归因：表选择遗漏；判分：missing_column: gold col 1 has no matching result column
- Agent 结果预览：`[{"年": 2025, "月": 1, "净销售额": 3434531.25}, {"年": 2025, "月": 2, "净销售额": 3218425.16}, {"年": 2025, "月": 3, "净销售额": 3514714.48}, {"年": 2025, "月": 4, "净销售额": 3452482.05}, {"年": 2025, "月": 5, "净销售额": 3560191`
- Agent SQL：
```sql
SELECT 
  d.year AS 年,
  d.month AS 月,
  SUM(f.pay_amount) - COALESCE(SUM(r.refund_amount), 0) AS 净销售额
FROM fact_order f
JOIN dim_date d ON f.date_id = d.date_id
LEFT JOIN fact_refund r ON f.date_id = r.date_id AND f.order_id = r.order_id
WHERE f.order_status != '已取消' 
  AND d.year = 2025
GROUP BY d.year, d.month
ORDER BY d.year, d.month;
```
- 标准 SQL：
```sql
SELECT d.month, SUM(o.pay_amount) - COALESCE(SUM(r.refund_amount), 0) AS net_sales
FROM fact_order o
JOIN dim_date d ON o.date_id = d.date_id
LEFT JOIN fact_refund r ON r.order_id = o.order_id
WHERE d.year = 2025 AND o.order_status <> '已取消'
GROUP BY d.month ORDER BY d.month
```

### f06 2025年各渠道的净销售额分别是多少？
- 归因：表选择遗漏；判分：missing_column: gold col 1 has no matching result column
- Agent 结果预览：`[{"渠道": "京东", "净销售额": 8144439.69}, {"渠道": "微信小程序", "净销售额": 16268741.12}, {"渠道": "自营App", "净销售额": 12579275.8}, {"渠道": "天猫", "净销售额": 7389579.66}, {"渠道": "H5商城", "净销售额": 3489337.28}]`
- Agent SQL：
```sql
SELECT 
  dc.channel_name AS 渠道,
  SUM(fo.pay_amount) - COALESCE(SUM(fr.refund_amount), 0) AS 净销售额
FROM fact_order fo
JOIN dim_channel dc ON fo.channel_id = dc.channel_id
LEFT JOIN fact_refund fr ON fo.date_id = fr.date_id AND fo.order_id = fr.order_id
WHERE fo.date_id >= 20250101 AND fo.date_id <= 20251231
  AND fo.order_status != '已取消'
GROUP BY dc.channel_name;
```
- 标准 SQL：
```sql
SELECT c.channel_name, SUM(o.pay_amount) - COALESCE(SUM(r.refund_amount), 0) AS net_sales
FROM fact_order o
JOIN dim_date d ON o.date_id = d.date_id
JOIN dim_channel c ON o.channel_id = c.channel_id
LEFT JOIN fact_refund r ON r.order_id = o.order_id
WHERE d.year = 2025 AND o.order_status <> '已取消'
GROUP BY c.channel_name
```

### f08 2025年双11大促期间各渠道的转化率分别是多少？
- 归因：SQL逻辑/口径错误；判分：missing_column: gold col 1 has no matching result column
- Agent 结果预览：`[{"渠道": "微信小程序", "转化率": 0.0548}, {"渠道": "自营App", "转化率": 0.0607}, {"渠道": "H5商城", "转化率": 0.0297}, {"渠道": "天猫", "转化率": 0.0385}, {"渠道": "京东", "转化率": 0.0421}]`
- Agent SQL：
```sql
SELECT 
  dc.channel_name AS 渠道,
  SUM(fo.order_count) / SUM(ft.visitors) AS 转化率
FROM dim_channel dc
INNER JOIN (
  SELECT 
    channel_id,
    COUNT(*) AS order_count
  FROM fact_order fo
  INNER JOIN dim_date dd ON fo.date_id = dd.date_id
  WHERE dd.holiday_name = '双11大促' 
    AND fo.order_status != '已取消'
  GROUP BY channel_id
) fo ON dc.channel_id = fo.channel_id
INNER JOIN (
  SELECT 
    channel_id,
    SUM(visitors) AS visitors
  FROM fact_traffic ft
  INNER JOIN dim_date dd ON ft.date_id = dd.date_id
  WHERE dd.holiday_name = '双11大促'
  GROUP BY channel_id
) ft ON dc.channel_id = ft.channel_id
GROUP BY dc.channel_name;
```
- 标准 SQL：
```sql
SELECT c.channel_name, od.order_cnt / tf.visitors AS conversion_rate
FROM dim_channel c
JOIN (
  SELECT o.channel_id, COUNT(*) AS order_cnt
  FROM fact_order o JOIN dim_date d ON o.date_id = d.date_id
  WHERE d.year = 2025 AND d.holiday_name = '双11大促' AND o.order_status <> '已取消'
  GROUP BY o.channel_id
) od ON od.channel_id = c.channel_id
JOIN (
  SELECT t.channel_id, SUM(t.visitors) AS visitors
  FROM fact_traffic t JOIN dim_date d ON t.date_id = d.date_id
  WHERE d.year = 2025 AND d.holiday_name = '双11大促'
  GROUP BY t.channel_id
) tf ON tf.channel_id = c.channel_id
```

### f09 2025年每个月的转化率分别是多少？
- 归因：SQL逻辑/口径错误；判分：missing_column: gold col 1 has no matching result column
- Agent 结果预览：`[{"月份": 1, "转化率": 0.0279}, {"月份": 2, "转化率": 0.0313}, {"月份": 3, "转化率": 0.0298}, {"月份": 4, "转化率": 0.0292}, {"月份": 5, "转化率": 0.0286}]`
- Agent SQL：
```sql
SELECT 
  d.month AS 月份,
  SUM(CASE WHEN o.order_status != '已取消' THEN 1 ELSE 0 END) / SUM(t.visitors) AS 转化率
FROM dim_date d
INNER JOIN fact_traffic t ON d.date_id = t.date_id
INNER JOIN fact_order o ON d.date_id = o.date_id
WHERE d.year = 2025
GROUP BY d.month
ORDER BY d.month;
```
- 标准 SQL：
```sql
SELECT od.month, od.order_cnt / tf.visitors AS conversion_rate
FROM (
  SELECT d.month, COUNT(*) AS order_cnt
  FROM fact_order o JOIN dim_date d ON o.date_id = d.date_id
  WHERE d.year = 2025 AND o.order_status <> '已取消'
  GROUP BY d.month
) od
JOIN (
  SELECT d.month, SUM(t.visitors) AS visitors
  FROM fact_traffic t JOIN dim_date d ON t.date_id = d.date_id
  WHERE d.year = 2025
  GROUP BY d.month
) tf ON tf.month = od.month
ORDER BY od.month
```

### f11 2025年各主营品类的店铺转化率分别是多少？
- 归因：SQL逻辑/口径错误；判分：missing_column: gold col 1 has no matching result column
- Agent 结果预览：`[{"主营品类": "手机数码", "转化率": 0.1104}, {"主营品类": "家用电器", "转化率": 0.1071}, {"主营品类": "美妆护肤", "转化率": 0.1177}, {"主营品类": "服饰鞋包", "转化率": 0.1045}, {"主营品类": "食品生鲜", "转化率": 0.0944}]`
- Agent SQL：
```sql
SELECT 
  ds.main_category AS 主营品类,
  SUM(fo.order_count) / SUM(ft.visitors) AS 转化率
FROM fact_traffic ft
JOIN dim_shop ds ON ft.shop_id = ds.shop_id
JOIN dim_date dd ON ft.date_id = dd.date_id
JOIN (
  SELECT 
    shop_id, 
    date_id, 
    COUNT(*) AS order_count
  FROM fact_order
  WHERE order_status != '已取消'
    AND date_id >= 20250101 
    AND date_id <= 20251231
  GROUP BY shop_id, date_id
) fo ON ft.shop_id = fo.shop_id AND ft.date_id = fo.date_id
WHERE dd.year = 2025
GROUP BY ds.main_category;
```
- 标准 SQL：
```sql
SELECT s.main_category, SUM(od.order_cnt) / SUM(tf.visitors) AS conversion_rate
FROM dim_shop s
JOIN (
  SELECT o.shop_id, COUNT(*) AS order_cnt
  FROM fact_order o JOIN dim_date d ON o.date_id = d.date_id
  WHERE d.year = 2025 AND o.order_status <> '已取消'
  GROUP BY o.shop_id
) od ON od.shop_id = s.shop_id
JOIN (
  SELECT t.shop_id, SUM(t.visitors) AS visitors
  FROM fact_traffic t JOIN dim_date d ON t.date_id = d.date_id
  WHERE d.year = 2025
  GROUP BY t.shop_id
) tf ON tf.shop_id = s.shop_id
GROUP BY s.main_category
```

### g03 新客订单的客单价是多少？
- 归因：指标选择错误；判分：missing_column: gold col 0 has no matching result column
- Agent 结果预览：`[{"客单价": 1463.931552}]`
- Agent SQL：
```sql
SELECT SUM(pay_amount) / COUNT(*) AS 客单价 FROM fact_order WHERE order_status != '已取消' AND is_new_customer = 1
```
- 标准 SQL：
```sql
SELECT SUM(gross_amount) / COUNT(*) AS aov
FROM fact_order
WHERE is_new_customer = 1 AND order_status <> '已取消'
```

### g06 用了优惠券的订单的客单价是多少？
- 归因：SQL逻辑/口径错误；判分：missing_column: gold col 0 has no matching result column
- Agent 结果预览：`[{"客单价": 1370.314325}]`
- Agent SQL：
```sql
SELECT SUM(pay_amount) / COUNT(*) AS 客单价 FROM fact_order WHERE order_status != '已取消' AND coupon_id IS NOT NULL
```
- 标准 SQL：
```sql
SELECT SUM(gross_amount) / COUNT(*) AS aov
FROM fact_order
WHERE coupon_id IS NOT NULL AND order_status <> '已取消'
```

### g10 2025年各城市线级的GMV分别是多少？
- 归因：SQL逻辑/口径错误；判分：missing_column: gold col 1 has no matching result column
- Agent 结果预览：`[{"城市线级": "新一线", "GMV": 27058713.82}, {"城市线级": "二线", "GMV": 10991589.44}, {"城市线级": "一线", "GMV": 11811397.62}, {"城市线级": "三线及以下", "GMV": 2946208.38}]`
- Agent SQL：
```sql
SELECT 
  dr.city_tier AS 城市线级,
  SUM(fo.pay_amount) AS GMV
FROM fact_order fo
JOIN dim_region dr ON fo.region_id = dr.region_id
JOIN dim_date dd ON fo.date_id = dd.date_id
WHERE dd.year = 2025
  AND fo.order_status != '已取消'
GROUP BY dr.city_tier;
```
- 标准 SQL：
```sql
SELECT r.city_tier, SUM(o.gross_amount) AS gmv
FROM fact_order o
JOIN dim_region r ON o.region_id = r.region_id
JOIN dim_date d ON o.date_id = d.date_id
WHERE d.year = 2025 AND o.order_status <> '已取消'
GROUP BY r.city_tier
```

### h01 2025年的GMV同比增长了多少？
- 归因：SQL逻辑/口径错误；判分：missing_column: gold col 0 has no matching result column
- Agent 结果预览：`[{"GMV同比增长率": 22.892233}]`
- Agent SQL：
```sql
SELECT 
  (SUM(CASE WHEN d.year = 2025 THEN f.pay_amount ELSE 0 END) - SUM(CASE WHEN d.year = 2024 THEN f.pay_amount ELSE 0 END)) / NULLIF(SUM(CASE WHEN d.year = 2024 THEN f.pay_amount ELSE 0 END), 0) * 100 AS `GMV同比增长率`
FROM fact_order f
JOIN dim_date d ON f.date_id = d.date_id
WHERE d.year IN (2024, 2025)
  AND f.order_status != '已取消';
```
- 标准 SQL：
```sql
SELECT SUM(CASE WHEN d.year = 2025 THEN o.gross_amount END)
       / SUM(CASE WHEN d.year = 2024 THEN o.gross_amount END) - 1 AS yoy_growth
FROM fact_order o JOIN dim_date d ON o.date_id = d.date_id
WHERE d.year IN (2024, 2025) AND o.order_status <> '已取消'
```

### h02 本月GMV环比上个月增长了多少？
- 归因：SQL逻辑/口径错误；判分：missing_column: gold col 0 has no matching result column
- Agent 结果预览：`[{"GMV环比增长率": -0.43646}]`
- Agent SQL：
```sql
SELECT 
  (SUM(CASE WHEN d.month = 12 THEN f.pay_amount END) - SUM(CASE WHEN d.month = 11 THEN f.pay_amount END)) / NULLIF(SUM(CASE WHEN d.month = 11 THEN f.pay_amount END), 0) AS `GMV环比增长率`
FROM fact_order f
JOIN dim_date d ON f.date_id = d.date_id
WHERE f.order_status != '已取消'
  AND d.date_id >= 20251101 AND d.date_id <= 20251231
  AND d.month IN (11, 12);
```
- 标准 SQL：
```sql
SELECT SUM(CASE WHEN d.month = 12 THEN o.gross_amount END)
       / SUM(CASE WHEN d.month = 11 THEN o.gross_amount END) - 1 AS mom_growth
FROM fact_order o JOIN dim_date d ON o.date_id = d.date_id
WHERE d.year = 2025 AND d.month IN (11, 12) AND o.order_status <> '已取消'
```

### h03 手机数码品类的销售额占总销售额的比例是多少？
- 归因：表选择遗漏；判分：missing_column: gold col 0 has no matching result column
- Agent 结果预览：`[{"手机数码品类销售额占比": 0.561592}]`
- Agent SQL：
```sql
SELECT 
  SUM(CASE WHEN d.category_l1 = '手机数码' THEN f.item_amount ELSE 0 END) / SUM(f.item_amount) AS `手机数码品类销售额占比`
FROM fact_order_item f
JOIN dim_product d ON f.product_id = d.product_id;
```
- 标准 SQL：
```sql
SELECT SUM(CASE WHEN p.category_l1 = '手机数码' THEN i.item_amount END) / SUM(i.item_amount) AS ratio
FROM fact_order_item i
JOIN fact_order o ON i.order_id = o.order_id
JOIN dim_product p ON i.product_id = p.product_id
WHERE o.order_status <> '已取消'
```
