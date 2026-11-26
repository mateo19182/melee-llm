"""farm.learner.shift: an action's advantage is the one of the frame it lands on."""
import torch
from farm.learner import shift


def test_shift():
    adv = torch.arange(10.0)[None].repeat(2, 1)
    done = torch.zeros(2, 10, dtype=torch.bool)
    done[1, 4] = True  # the transition of frame 4 ends the game
    assert shift(adv, done, 0) is adv
    out = shift(adv, done, 3)
    assert out[0].tolist() == [3, 4, 5, 6, 7, 8, 9, 0, 0, 0]
    # chosen at 0 and 1: land at 3 and 4, in time. Chosen at 2..4: the game ends first. From 5 on: the next game.
    assert out[1].tolist() == [3, 4, 0, 0, 0, 8, 9, 0, 0, 0]
