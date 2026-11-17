#!/usr/bin/env bash
# Run fortress suites (melee_llm.solver.fortress) as a user service with a hard memory limit, like search.sh.
# Finished games are kept in data/fortress/NAME.jsonl; a restart continues from there.
#   scripts/fortress.sh NAME [--mem GB] -- map@8 ledge@6 hop@6 ...
set -euo pipefail
cd "$(dirname "$0")/.."
NAME=$1; shift
MEM=12
[ "${1:-}" = "--mem" ] && { MEM=$2; shift 2; }
[ "${1:-}" = "--" ] && shift
mkdir -p data/fortress
systemd-run --user --unit="$NAME" --collect --working-directory="$PWD" \
  -p MemoryMax="${MEM}G" -p MemorySwapMax=0 -p OOMScoreAdjust=1000 -p Nice=10 \
  ${MSL_DATA_DIR:+--setenv=MSL_DATA_DIR="$MSL_DATA_DIR"} \
  -p Restart=on-failure -p RestartSec=60 \
  bash -c ".venv/bin/python -m melee_llm.solver.fortress suite --workers ${WORKERS:-7} --out data/fortress/$NAME.jsonl $* >> data/fortress/$NAME.txt 2>&1"
echo "started $NAME (limit ${MEM} GB): data/fortress/$NAME.txt, stop with: systemctl --user stop $NAME"
