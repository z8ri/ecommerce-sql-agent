# 问数评测

回答一个问题：**这个 Agent 到底有多准，每次改动是变好还是变坏？**

## 组成

| 文件 | 作用 |
|---|---|
| `dataset.yaml` | 92 道题，每题带标准 SQL，按题型和难度打标签 |
| `validate_gold.py` | 校验标准 SQL 可执行、结果非空、排名题没有并列 |
| `compare.py` | 判分：比较 Agent 结果集和标准结果集是否等价（`tests/test_compare.py` 覆盖） |
| `runner.py` | 驱动 LangGraph 跑全部题目，截取每个节点的中间输出，写入 `runs/` |
| `report.py` | 从原始记录计算指标，支持多次运行的稳定性汇总 |

## 指标

- **EX（执行准确率）**：Agent 的 SQL 执行结果与标准结果等价的题目占比。只比答案，不比写法。
- **分阶段指标**：取值召回率、指标召回/选择准确率、表召回率，用来定位错在哪一环。
- **失败归因**：每道失败题归到 执行失败 / 取值召回遗漏 / 指标选择错误 / 表选择遗漏 / SQL 逻辑错误。
- **校验抓不到的语义错误**：首次生成就通过 EXPLAIN 的 SQL 中，答案仍然错误的比例。
- 延迟、LLM 调用次数、token 消耗。

## 用法

```bash
uv run python -m eval.validate_gold                      # 校验评测集
uv run pytest                                            # 比对器单测
uv run python -m eval.runner --name baseline             # 跑全量
uv run python -m eval.runner --name x --ids a01,b01      # 只跑几题
uv run python -m eval.report baseline                    # 单次报告（同时写入 runs/baseline.md）
uv run python -m eval.report baseline baseline_r2 baseline_r3   # 多次运行：对比 + 稳定性
```

## 方法论上的两点说明

1. **单次运行不可信。** 同一配置的三次基线 EX 分别是 72.8%、78.3%、84.8%（温度已设为 0）。
   比较两个版本时，每个版本至少跑 3 次，看均值和波动，而不是看单次。
2. **评测集和元数据配置出自同一个作者，不是独立的。** 标准 SQL 里的统一口径（有效订单排除已取消、
   销售额默认指 GMV 等）与 `conf/meta_config.yaml` 里的指标口径是一致的，这是有意的：评测衡量的是
   “Agent 能否严格按已写明的口径作答”，而不是“能否猜对口径”。代价是它不能反映口径本身是否合理。
   做对外对比时，应该补一批由他人独立编写的题目。
