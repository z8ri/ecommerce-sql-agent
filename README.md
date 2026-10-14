# 电商问数 Agent

自然语言查询电商数仓的 Text-to-SQL Agent（LangGraph）。重点不在“能跑”，而在**可度量**：
92 道带标准答案的评测集、分阶段诊断、逐项消融，以及对 LLM 生成 SQL 的安全约束。

> 本项目基于开源教程项目 [didilili/shopkeeper-agent](https://github.com/didilili/shopkeeper-agent)（MIT）二次开发，
> 上游原始 README 保存在 [docs/upstream-README.md](docs/upstream-README.md)。
> 上游提供的是基础的检索增强问数流程；评测、数据、口径修复、自纠错、安全约束是在此之上新增的部分，见下文。

## 相对上游新增了什么

| 方向 | 内容 |
|---|---|
| 数据 | 把 5 张表的教学数仓换成 11 张表的多渠道电商星型模型（约 7 万订单、10.6 万订单明细、5.3 万流量记录），固定随机种子生成，结果可复现；数据里刻意埋了口径陷阱（已取消订单、退款分表、流量与订单粒度不同） |
| 评测 | 92 题评测集 + 执行结果比对判分 + 分阶段指标 + 失败归因 + 多次运行的稳定性统计，见 [eval/README.md](eval/README.md) |
| 修复（由评测发现） | ① 表过滤后补回指标依赖字段 ② 指标粒度口径写入语义层 ③ 相对时间表达用代码解析 ④ 有界自纠错循环 + 结果复核 |
| 安全 | 只读数据库账号 + SQL 语法树检查 + 行数上限，命中规则的请求直接拒绝而不是“修正” |
| 工程 | 嵌入服务可切换（百炼 / 本地 TEI）、ES/Qdrant 超时重试、知识库可重复构建（`--reset`）、各项能力都有开关便于消融 |

## 结果

三次运行的执行准确率（EX）均值，92 题，同一配置重复运行 3 次（单次运行波动可达 12 个百分点，所以不看单次）：

| 配置 | EX 均值 ± 标准差 |
|---|---|
| 上游原始流程（基线） | 78.6% ± 6.0 |
| + 补回指标依赖字段（对照：同代码关闭该开关 76.4% ± 1.3） | 85.5% ± 2.3 |
| + GMV 粒度口径 | 90.6% ± 0.6 |
| + 时间表达代码解析 | 90.9% ± 0.6 |
| + 自纠错循环与结果复核 | 92.0% ± 3.5 |
| + 安全护栏 | 91.7% ± 2.3 |

按题型看，改动的价值比总分更清楚：相对时间类题目从 33% 到 100%，指标口径类 74.5% 到 90.6%，跨事实表类 51.9% 到 63.0%。
完整的数字、退步案例和方法说明见 [docs/results.md](docs/results.md)。

## 流程

```
问题 → 抽关键词 → 字段 / 取值 / 指标 三路召回 → 合并 → 表过滤 ∥ 指标过滤
     → 补回指标依赖字段 → 额外上下文（含相对时间解析）→ 生成 SQL
     → 安全检查 + EXPLAIN 校验 → 执行（只读账号）→ 结果复核 → 返回
                 ↑                                        │
                 └──────────── 修复 SQL（最多 2 次）←───────┘
          命中安全规则 → 直接拒绝（不进入修复）
```

## 诚实的局限

- **评测集和语义层出自同一作者**，不是独立标注。它衡量的是“能否严格按已写明的口径作答”。
- **统计力度有限**：92 题，每配置 3 次，标准差 1 到 3.5 个点。补字段（+9）和粒度口径（+5）的提升是明确的；
  自纠错循环整体 +1.1 个点，**与前一组的波动范围重叠，不能算显著**，它真正有效的是跨事实表这一类题，代价是 token 增加约 37%、延迟增加约 30%。
- **复核环节的最新改动没有测量过**：自纠错的结果复核最初有明显误报（56 次触发修正里 13 次真修好、10 次改坏），
  之后针对性修改了复核逻辑（去掉会误导它的信息、丢弃自相矛盾的判定），但这版没有重新跑评测。上表数字对应修改前的版本。
- **带护栏版本的完整安全评测记录缺失**：只保留了无护栏对照（沙箱库）的结果；带护栏版本跑过一次，
  16 条攻击均安全，但其中两条正常问题因接口欠费没有出结果，该次结果未保留，需要重跑才有可复现记录。
- 数据是仿真数据；前端沿用上游，没有随这些改动更新或验证。

## 快速开始

需要 Python 3.14、`uv`、Docker，以及阿里云百炼的 API Key（LLM 和 Embedding 共用）。

```bash
uv sync
cp .env.example .env                       # 填入 LLM_API_KEY
docker compose -f docker/docker-compose.yaml up -d mysql elasticsearch qdrant
uv run python -m app.scripts.seed_dw       # 生成并导入演示数仓
uv run python -m app.scripts.build_meta_knowledge -c conf/meta_config.yaml --reset
uv run fastapi dev main.py                 # POST /api/query {"query": "2025年各渠道的转化率"}
```

评测与消融：

```bash
uv run python -m eval.validate_gold                                   # 校验标准答案
uv run pytest                                                         # 单元测试
eval/run3.sh mytag                                                    # 快照 + 并行跑 3 次
AGENT_SELF_CORRECT=false eval/run3.sh noloop                          # 关掉某项能力做消融
uv run python -m eval.report --groups noloop mytag                    # 按组对比
```

可用开关（环境变量，默认全开）：`AGENT_PIN_METRIC_COLUMNS`、`AGENT_RESOLVE_TIME`、`AGENT_SELF_CORRECT`、`AGENT_SQL_GUARD`。

> 一次完整评测约消耗 100 万到 150 万 token，3 次重复约 300 万到 450 万。做对比实验前先估好预算。

## 目录

```
app/agent/          LangGraph 图、节点、时间解析、SQL 安全检查
app/scripts/        seed_dw（造数）、build_meta_knowledge（构建知识库）
conf/               应用配置、语义层（表 / 字段 / 指标口径）
eval/               评测集、判分、运行器、报告、安全评测
docs/               结果分析、面试说明、上游 README
tests/              单元测试（判分器、时间解析、SQL 检查、复核）
```
