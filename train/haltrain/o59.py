"""HAL's training script, experiments/059_muon_action_sequence.py, as an importable module.

Its file name is not a valid module name, and loader worker processes must be able to import the classes it
defines by module path. So this module runs the script's source in its own namespace; nothing is copied.
"""
from pathlib import Path

_SOURCE = Path(__file__).resolve().parents[2] / "vendor/hal/experiments/059_muon_action_sequence.py"
exec(compile(_SOURCE.read_text(), str(_SOURCE), "exec"), globals())
