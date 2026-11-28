#!/bin/bash
# Farm evaluations of a Yoshi fine-tune (the list in docs/experiments/E36-own-yoshi.md):
#   train/own/eval-yoshi.sh RUN STEP [GAMES]     e.g. train/own/eval-yoshi.sh own-yoshi-ft 0122070
# RUN/STEP may also be the base (own-pre-10m-b 0793457) for the same matches. Name codes as in eval.sh.
R=$(cd "$(dirname "$0")/../.." && pwd); K=$R/data/train/runs; N=${3:-64}
NEW="faynt:$K/$1/ckpt/step-$2"; BASE="faynt:$K/own-pre-10m-b/ckpt/step-0793457"; O="items=4,own=1"
cd "$R/train" || exit 1
run() {
  echo "== $1 vs $2"
  PYTHONPATH=. "$R/vendor/Faynt-Tournament/.venv/bin/python" -m farm.run "$1" "$2" --games "$N" --lanes 32 2>&1 |
    grep -v Warn | tail -3 | sed "s|$K/||g"
}
if [ "$NEW" != "$BASE" ]; then
  run "$NEW,name=14,$O/YOSHI" "$BASE,name=14,$O/YOSHI"
  run "$NEW,name=15,delay=12,$O/YOSHI" "$BASE,name=15,delay=12,$O/YOSHI"
fi
for code in 14 18; do
  run "$NEW,name=$code,$O/YOSHI" "faynt:10M-Base/YOSHI"
  run "$NEW,name=$((code + 1)),delay=12,$O/YOSHI" "faynt:$K/yoshi-rl-3-ladder/ckpt/step-01795,delay=12,own=1/YOSHI"
done
run "$NEW,name=15,delay=12,$O/YOSHI" "phillip:yoshi_d18_ditto/YOSHI"
echo done
