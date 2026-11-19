"""ExiAIController sends each trigger value that the ExiAI build maps to the raw value libmelee intends.

The build reads a pipe trigger value v as round(510 v - 255) (round half to even), clipped to 0..140: measured over
1,025 values through Dolphin on 2026-11-19 (docs/experiments/E30-exi-triggers.md).
"""
import melee

from melee_llm.runner import ExiAIController


def exiai_reads(v: float) -> int:
    return min(140, max(0, round(510 * v - 255)))


def test_every_amount_lands_on_libmelee_raw():
    sent = []
    c = ExiAIController.__new__(ExiAIController)
    c.current, c._check_pipe = melee.ControllerState(), lambda: None
    c._write = sent.append
    for i in range(1001):
        amount = i / 1000
        c.press_shoulder(melee.Button.BUTTON_L, amount)
        v = float(sent[-1].split()[2])
        assert exiai_reads(v) == round(amount * 140), (amount, v)
        assert c.current.l_shoulder == amount
