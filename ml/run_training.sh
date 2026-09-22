#!/usr/bin/env bash
set -euo pipefail

ML_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
YOLO_PYTHON="/home/choi-chun-hwan/venv/yolo-venv/bin/python"

if [[ ! -x "$YOLO_PYTHON" ]]; then
  echo "YOLO Python을 찾지 못했습니다: $YOLO_PYTHON" >&2
  exit 1
fi

echo "절전 차단 상태로 YOLO 학습을 시작합니다."
echo "로그: $ML_ROOT/train.log"

systemd-inhibit \
  --what=sleep \
  --mode=block \
  --why="YOLO overnight training" \
  "$YOLO_PYTHON" -u "$ML_ROOT/train_yolo.py" "$@" \
  2>&1 | tee -a "$ML_ROOT/train.log"
