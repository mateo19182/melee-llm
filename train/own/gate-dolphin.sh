#!/bin/bash
# E34 on Dolphin: is the gate model weaker there than in the farm, and does reading its own pad matter?
cd /home/mateo/projects/ai/melee-llm/train
L() { DISPLAY=:99 uv run python -m meleebot.league play "$1" --opponents "$2" --games $3 --parallel 4 2>&1 | grep " vs \|rror" | cut -c1-200; }
L "faynt:own-gate-mix,name=0,items=4/FOX" cpu9-fox 12
L "faynt:own-gate-mix,own=1,name=0,items=4/FOX" cpu9-fox 12
L "faynt:own-gate-mix,own=1,name=0,items=4/FOX" "faynt:10M-Base/FOX" 8
echo done
