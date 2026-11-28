#!/bin/bash
# E36 on Dolphin: the Yoshi fine-tune at no delay against CPU 9 and HAL's aMSa Yoshi, 24 games each.
# Needs vendor/Faynt-Tournament/weights/Faynt-own-yoshi-ft -> the run's final checkpoint.
cd /home/mateo/projects/ai/melee-llm/train
L() { DISPLAY=:99 uv run python -m meleebot.league play "$1" --opponents "$2" --games $3 --parallel 4 2>&1 | grep " vs \|rror" | cut -c1-200; }
L "faynt:own-yoshi-ft,own=1,name=18,items=4/YOSHI" cpu9-fox,hal-amsa-yoshi 24
echo done
