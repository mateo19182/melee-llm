#!/bin/bash
# E34 follow-up: enough Dolphin games to compare with the farm (ours vs Faynt Base 42% there).
cd /home/mateo/projects/ai/melee-llm/train
L() { DISPLAY=:99 uv run python -m meleebot.league play "$1" --opponents "$2" --games $3 --parallel 4 2>&1 | grep " vs \|rror" | cut -c1-200; }

L "faynt:own-gate-mix,own=1,name=0,items=4,threads=4/FOX" "faynt:10M-Base/FOX" 40
echo done
