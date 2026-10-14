#!/usr/bin/env bash
# 把当前工作区代码复制成评测快照：eval/snapshot.sh <快照名>
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
snap="/tmp/shopkeeper_snapshot_$1"
rm -rf "$snap" && mkdir -p "$snap"
rsync -a --exclude '.venv' --exclude '.git' --exclude 'eval/runs' --exclude 'logs' \
      --exclude 'frontend' --exclude 'docker' --exclude 'docs' --exclude '__pycache__' \
      --exclude '.pytest_cache' --exclude '.ruff_cache' "$root/" "$snap/"
git -C "$root" rev-parse --short HEAD > "$snap/SNAPSHOT_BASE_COMMIT" 2>/dev/null || true
git -C "$root" status --short > "$snap/SNAPSHOT_UNCOMMITTED" 2>/dev/null || true
echo "快照已创建：$snap"
