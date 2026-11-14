"""Phillip vs Phillip in melee-sim-light through slippi-ai's own evaluator (see docs/simulator.md).

Run from vendor/slippi-ai with the sim venv:
  MSL_DATA_DIR=../melee-sim-light/data JAX_PLATFORMS=cpu ../sim-venv/bin/python \
    ../../scripts/sim_phillip_eval.py --sim_envs --num_envs=1 --num_games=1 \
    --player.ai.path=models/gm.onnx --player.character=FOX \
    --opponent.ai.path=models/gold.onnx --opponent.character=FOX

slippi-ai @ 5ada33e looks players up by `present`, which melee_sim clears for an eliminated
player, so every game that ends on stocks crashes. The two lookups below match on
`source_player` alone (255 marks an unused slot).
"""
import runpy
import sys

import numpy as np
from slippi_ai.sim_env import env as env_mod
from slippi_ai.sim_env import observations as obs_mod


def _slot_for_source(slots, source_player):
  for i in range(slots.shape[1]):
    if np.all(slots[:, i]['source_player'] == int(source_player)):
      return slots[:, i]
  raise RuntimeError(f'no slot for source player {source_player}')


def _slots_by_source(slots):
  result = {}
  for i in range(slots.shape[1]):
    source = slots[:, i]['source_player']
    if source[0] != 255 and np.all(source == source[0]):
      result[int(source[0])] = slots[:, i]
  if 0 not in result or 1 not in result:
    raise RuntimeError('melee_sim gamestate did not contain source players 0 and 1')
  return result


env_mod._slot_for_source = _slot_for_source
obs_mod._slots_by_source = _slots_by_source
sys.argv = ['run_evaluator.py'] + sys.argv[1:]
runpy.run_path('scripts/run_evaluator.py', run_name='__main__')
