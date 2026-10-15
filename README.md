# E-commerce SQL Agent · 电商问数智能体

用自然语言查询电商数据仓库的 Text-to-SQL Agent，基于 LangGraph 构建。

它不只是“把问题翻译成 SQL”：围绕**业务口径是否算对**做了一整套工程——
92 道带标准答案的评测集、分阶段的错误诊断、逐项消融实验、结果自检与修复、以及对大模型生成 SQL 的安全约束。

```
用户：2025 年各渠道的转化率是多少？
Agent：召回相关字段 / 指标口径 → 分别聚合订单与流量 → 生成 SQL → 安全检查 → 只读执行 → 复核结果 → 返回
```

## 特点

| | |
|---|---|
| **检索增强的口径对齐** | 字段、字段取值、指标三路混合召回（Qdrant 向量 + Elasticsearch 全文 + MySQL 元数据），把“销售额默认指 GMV、GMV 排除已取消订单”这类口径作为权威上下文交给模型 |
| **可度量** | 92 题评测集，按结果集等价判分（只比答案，不比写法），支持分阶段指标、失败归因、多次运行稳定性统计 |
| **由评测驱动的修复** | 表过滤后补回指标依赖字段；指标粒度口径；相对时间表达由代码解析；有界自纠错循环 + 结果复核 |
| **安全约束** | 只读数据库账号 + 语法树级 SQL 检查 + 行数上限；命中规则直接拒绝，不进入修复 |
| **可消融** | 每项能力都有开关，可以在同一份代码快照上只切换一个开关做严格对照 |

## 效果

92 题，同一配置重复运行 3 次取均值（单次运行的波动可达 12 个百分点，所以不看单次）：

| 配置 | 执行准确率 (EX) |
|---|---|
| 基础检索增强流程 | 78.6% ± 6.0 |
| + 补回指标依赖字段（对照：同代码关闭该开关 76.4% ± 1.3） | 85.5% ± 2.3 |
| + GMV 粒度口径 | 90.6% ± 0.6 |
| + 时间表达代码解析 | 90.9% ± 0.6 |
| + 自纠错循环与结果复核 | 92.0% ± 3.5 |
| + 安全护栏 | 91.7% ± 2.3 |

分题型看更有信息量：相对时间类 33% → 100%，指标口径类 74.5% → 90.6%，多表连接类 74.4% → 92.3%，跨事实表类 51.9% → 63.0%。
逐项分析、退步案例与方法说明见 [docs/results.md](docs/results.md)。

## 流程

```
问题 → 抽关键词 → 字段 / 取值 / 指标 三路召回 → 合并 → 表过滤 ∥ 指标过滤
     → 补回指标依赖字段 → 额外上下文（含相对时间解析）→ 生成 SQL
     → 安全检查 + EXPLAIN 校验 → 执行（只读账号）→ 结果复核 → 返回
                 ↑                                        │
                 └──────────── 修复 SQL（最多 2 次）←───────┘
          命中安全规则 → 直接拒绝（不进入修复）
```

设计上的几个取舍：
- **确定性的事交给代码，不交给模型。** “上季度”的含义、指标依赖哪些字段、SQL 能不能执行，都是可以确定的，由代码处理；模型负责理解问题和写 SQL。
- **EXPLAIN 只能发现语法错误。** 一次生成就通过校验的 SQL 里仍有约两成答案是错的，所以执行后还要复核结果。
- **安全约束不依赖模型的自觉。** 三层相互独立：只读账号、语法树白名单检查、拒绝而不是修复。

## 技术栈

Python 3.14 · LangGraph · FastAPI（SSE 流式）· MySQL（数仓与元数据）· Qdrant · Elasticsearch（IK 分词）·
阿里云百炼（`qwen-plus` + `text-embedding-v4`，可切换本地 TEI）· sqlglot · pytest · React（前端）

## 快速开始

需要 Python 3.14、`uv`、Docker，以及阿里云百炼的 API Key（LLM 与 Embedding 共用）。

```bash
uv sync
cp .env.example .env                       # 填入 LLM_API_KEY
docker compose -f docker/docker-compose.yaml up -d mysql elasticsearch qdrant
uv run python -m app.scripts.seed_dw       # 生成并导入演示数仓（固定随机种子，结果可复现）
uv run python -m app.scripts.build_meta_knowledge -c conf/meta_config.yaml --reset
uv run fastapi dev main.py                 # POST /api/query  {"query": "2025年各渠道的转化率"}
```

演示数仓是一个多渠道电商星型模型：7 张维度表 + 4 张事实表（订单、订单明细、退款、流量），
约 7 万订单、10.6 万订单明细，数据中刻意包含口径陷阱（已取消订单、退款单独成表、流量与订单粒度不同）。

## 评测与消融

```bash
uv run python -m eval.validate_gold                        # 校验 92 条标准 SQL 可执行、结果非空、排名无并列
uv run pytest                                              # 单元测试（判分器、时间解析、SQL 检查、结果复核）
eval/run3.sh mytag                                         # 复制代码快照后并行跑 3 次
AGENT_SELF_CORRECT=false eval/run3.sh noloop               # 关掉某项能力做消融
uv run python -m eval.report --groups noloop mytag         # 按组对比：均值、波动、逐题变化
uv run python -m eval.safety --name safety_guarded         # 22 条恶意 / 越权 / 拖垮数据库的提问
```

可用开关（环境变量，默认全开）：`AGENT_PIN_METRIC_COLUMNS`、`AGENT_RESOLVE_TIME`、`AGENT_SELF_CORRECT`、`AGENT_SQL_GUARD`。
评测方法与指标定义见 [eval/README.md](eval/README.md)。

> 一次完整评测约消耗 100 万到 150 万 token，重复 3 次约 300 万到 450 万。做对比实验前先估好预算。

## 已知局限

- 评测集与语义层（指标口径）出自同一作者，不是独立标注，衡量的是“能否严格按已写明的口径作答”。
- 样本量有限：92 题、每配置 3 次，标准差 1 到 3.5 个点。补字段与粒度口径的提升是明确的；
  自纠错循环整体 +1.1 个点，与前一组的波动范围重叠，不能算显著，它真正有效的是跨事实表这一类题，代价是 token 约 +37%、延迟约 +30%。
- 结果复核最初有明显误报，之后针对性修改了复核逻辑（见 [docs/results.md](docs/results.md)），**修改后的版本没有重新跑评测**，表中数字对应修改前。
- 带护栏版本的完整安全评测记录需要重跑才能复现；目前仓库里保留的是无护栏对照（一次性沙箱库）的结果。
- 使用仿真数据；前端沿用最初的实现，没有随后端改动更新或验证。

## 目录

```
app/agent/          LangGraph 图、各节点、时间解析、SQL 安全检查
app/scripts/        seed_dw（造数）、build_meta_knowledge（构建知识库）
conf/               应用配置、语义层（表 / 字段 / 指标口径）
eval/               评测集、判分、运行器、报告、安全评测
docs/               结果分析
tests/              单元测试
frontend/           React 前端
```

## 致谢与许可

项目的起点是开源教程项目 [shopkeeper-agent](https://github.com/didilili/shopkeeper-agent)（作者 didilili，MIT 许可证），
其基础的检索增强问数流程为本项目提供了出发点；原始 README 保留在 [docs/upstream-README.md](docs/upstream-README.md)。
数仓与数据、评测体系、口径修复、自纠错、安全约束等为后续新增。

本项目以 MIT 许可证发布，见 [LICENSE](LICENSE)。
