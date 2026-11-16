#!/usr/bin/env bash
# Run a long solver search as a user service with a hard memory limit, so a search that grows too far is the
# thing that gets killed, not the rest of the machine. Finished jobs are kept in data/solver/NAME.jsonl; running
# the same command again continues from there.
#   scripts/search.sh NAME [--mem GB] -- <arguments of melee_llm.solver.force>
#   MOD=nash scripts/search.sh NAME -- <arguments of melee_llm.solver.nash>
set -euo pipefail
cd "$(dirname "$0")/.."
NAME=$1; shift
MEM=24
[ "${1:-}" = "--mem" ] && { MEM=$2; shift 2; }
[ "${1:-}" = "--" ] && shift
mkdir -p data/solver
systemd-run --user --unit="$NAME" --collect --working-directory="$PWD" \
  -p MemoryMax="${MEM}G" -p MemorySwapMax=0 -p OOMScoreAdjust=1000 -p Nice=10 \
  bash -c ".venv/bin/python -m melee_llm.solver.${MOD:-force} --out data/solver/$NAME.jsonl $* >> data/solver/$NAME.txt 2>&1"
echo "started $NAME (limit ${MEM} GB): data/solver/$NAME.txt, stop with: systemctl --user stop $NAME"
