#!/bin/bash
# Farm evaluations of a checkpoint of the all-character pretrain (the list in docs/experiments/E35-own-pretrain.md):
#   train/own/eval.sh RUN STEP [GAMES]     e.g. train/own/eval.sh own-pre-10m 0976562
# Name codes are for --delays 0,12 (`python -m own.data 0,12`): pro winner 18/19, Master winner 14/15, Master
# loser 12/13 at delay 0/12. The gate model (E34) has no labels: 0 and 1.
R=$(cd "$(dirname "$0")/../.." && pwd); K=$R/data/train/runs; N=${3:-64}
NEW="faynt:$K/$1/ckpt/step-$2"; GATE="faynt:$K/own-gate-mix/ckpt/step-0122070"; O="items=4,own=1"
cd "$R/train" || exit 1
run() {
  echo "== $1 vs $2"
  PYTHONPATH=. "$R/vendor/Faynt-Tournament/.venv/bin/python" -m farm.run "$1" "$2" --games "$N" --lanes 32 2>&1 |
    grep -v Warn | tail -3 | sed "s|$K/||g"
}
for code in 18 14 12; do run "$NEW,name=$code,$O/FOX" "faynt:10M-Base/FOX"; done
for c in FOX YOSHI; do
  run "$NEW,name=18,$O/$c" "$GATE,name=0,$O/$c"
  run "$NEW,name=19,delay=12,$O/$c" "$GATE,name=1,delay=12,$O/$c"
done
run "$NEW,name=18,$O/YOSHI" "faynt:10M-Base/YOSHI"
run "$NEW,name=19,delay=12,$O/YOSHI" "faynt:$K/yoshi-rl-3-ladder/ckpt/step-01795,delay=12,own=1/YOSHI"
run "$NEW,name=19,delay=12,$O/YOSHI" "phillip:yoshi_d18_ditto/YOSHI"
echo done
