#!/usr/bin/env bash
# 同一配置并行跑 3 次，用于比较版本（单次运行波动很大，必须看均值）
# 用法：eval/run3.sh <标签>      例：eval/run3.sh pin
#       AGENT_PIN_METRIC_COLUMNS=false eval/run3.sh nopin     （环境变量会传给运行器，用于消融）
set -euo pipefail
tag="$1"
cd "$(dirname "$0")/.."
for i in 1 2 3; do
  uv run python -m eval.runner --name "${tag}_r${i}" --concurrency 2 > "/tmp/${tag}_r${i}.log" 2>&1 &
done
wait
grep -h "^EX =" /tmp/${tag}_r[123].log
