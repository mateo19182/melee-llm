#!/bin/bash
# E35 on Dolphin: the pretrain's Fox at no delay against CPU 9 (the bar) and Faynt 10M Base, per name code;
# `pre-dolphin.sh roster` plays the Fox roster at 12 games each.
# Needs vendor/Faynt-Tournament/weights/Faynt-own-pre-10m-b -> the run's final checkpoint.
cd /home/mateo/projects/ai/melee-llm/train
L() { DISPLAY=:99 uv run python -m meleebot.league play "$1" --opponents "$2" --games $3 --parallel 4 2>&1 | grep " vs \|rror" | cut -c1-200; }
if [ "$1" = roster ]; then
  L "faynt:own-pre-10m-b,own=1,name=14,items=4/FOX" phillip-plat-fox,phillip-diamond-fox,phillip-master-fox,phillip-gm-fox,phillip-super-gm-fox,phillip-fox-v6.2,mimic-fox,hal-master-fox,faynt-10m-fox,faynt-75m-fox 12
  echo done; exit
fi
for code in 14 18; do L "faynt:own-pre-10m-b,own=1,name=$code,items=4/FOX" cpu9-fox 24; done
L "faynt:own-pre-10m-b,own=1,name=14,items=4/FOX" "faynt:10M-Base/FOX" 24
echo done
