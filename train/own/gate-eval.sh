#!/bin/bash
# Final farm evaluations for E34, run once both gate runs have written their last checkpoint.
R=/home/mateo/projects/ai/melee-llm; K=$R/data/train/runs; LAST=step-0122070
until [ -f $K/own-gate-mix/ckpt/$LAST/model.safetensors ] && [ -f $K/own-gate-d0/ckpt/$LAST/model.safetensors ]; do sleep 120; done
sleep 60
cd $R/train
MIX="faynt:$K/own-gate-mix/ckpt/$LAST"; D0="faynt:$K/own-gate-d0/ckpt/$LAST"; O="items=4,own=1"
run() { echo "== $1 vs $2"; PYTHONPATH=. $R/vendor/Faynt-Tournament/.venv/bin/python -m farm.run "$1" "$2" --games 64 --lanes 32 2>&1 | grep -v Warn | tail -3 | sed "s|$K/||g"; }
run "$MIX,name=0,$O/FOX" "faynt:10M-Base/FOX"
run "$D0,name=0,$O/FOX" "faynt:10M-Base/FOX"
run "$MIX,name=0,$O/FOX" "$D0,name=0,$O/FOX"
run "$MIX,name=0,$O/YOSHI" "faynt:10M-Base/YOSHI"
run "$D0,name=0,$O/YOSHI" "faynt:10M-Base/YOSHI"
run "$MIX,name=1,delay=12,$O/YOSHI" "faynt:$K/yoshi-rl-3-ladder/ckpt/step-01795,delay=12,own=1/YOSHI"
run "$MIX,name=1,delay=12,$O/FOX" "faynt:10M-Base,delay=12,own=1/FOX"
run "$MIX,name=1,delay=12,$O/YOSHI" "phillip:yoshi_d18_ditto/YOSHI"
echo done
