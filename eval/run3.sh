#!/usr/bin/env bash
# 同一配置并行跑 3 次，用于比较版本（单次运行波动很大，必须看均值）
#
# 用法：eval/run3.sh <标签> [快照名]
#       不给快照名时，用当前代码新建一个以标签命名的快照；
#       给了快照名就复用已有快照（对比几个配置时，让它们跑同一份代码）：
#         eval/snapshot.sh v1;  A=1 eval/run3.sh a v1;  B=1 eval/run3.sh b v1
#       AGENT_PIN_METRIC_COLUMNS=false eval/run3.sh nopin     （环境变量会传给运行器，用于消融）
#
# 运行前先把当前代码复制成快照，再从快照里跑。这样评测期间继续改代码、改提示词
# 不会影响正在跑的评测（提示词是运行时读取的），每次结果也对应确定的代码版本。
set -euo pipefail
tag="$1"
root="$(cd "$(dirname "$0")/.." && pwd)"
snap_name="${2:-$tag}"
snap="/tmp/shopkeeper_snapshot_${snap_name}"
[ -n "${2:-}" ] || "$root/eval/snapshot.sh" "$snap_name"
[ -d "$snap" ] || { echo "快照不存在：$snap（先运行 eval/snapshot.sh $snap_name）"; exit 1; }

cd "$snap"
for i in 1 2 3; do
  EVAL_RUNS_DIR="$root/eval/runs" "$root/.venv/bin/python" -m eval.runner \
    --name "${tag}_r${i}" --concurrency 2 > "/tmp/${tag}_r${i}.log" 2>&1 &
done
wait
grep -h "^EX =" /tmp/${tag}_r[123].log
