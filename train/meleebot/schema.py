"""On-disk layout of the replay dataset.

frames.bin is one flat array of FRAME records: every kept game, one perspective after another.
games.npz has one row per perspective (offset and length into frames.bin, plus labels).

Frame i holds the state after frame i's inputs were applied, next to those inputs. A policy that
has seen frame i must therefore predict the controller of frame i+1 or later, never of frame i.
"""
import numpy as np

PLAYER = np.dtype([
    ("pos", "<f4", 2),
    ("vel", "<f2", 5),          # self_x_air, self_x_ground, self_y, knockback_x, knockback_y
    ("percent", "<f2"),
    ("shield", "<f2"),
    ("state_age", "<f2"),
    ("hitstun", "<f2"),         # frames left; 0 when not in hitstun
    ("action", "<u2"),
    ("hitlag", "u1"),
    ("stocks", "u1"),
    ("jumps", "u1"),
    ("facing", "i1"),           # -1 left, +1 right
    ("airborne", "u1"),
    ("invuln", "u1"),           # 0 vulnerable, 1 invulnerable, 2 intangible
])

CONTROLLER = np.dtype([
    ("stick", "i1", 2),         # -80..80, the grid the game reads
    ("cstick", "i1", 2),
    ("trigger", "u1", 2),       # analog L, R: 0..140
    ("buttons", "<u2"),         # physical bitmask, see BUTTONS
])

FRAME = np.dtype([("me", PLAYER), ("opp", PLAYER), ("me_pad", CONTROLLER), ("opp_pad", CONTROLLER)])

BUTTONS = {"DPAD_LEFT": 0x0001, "DPAD_RIGHT": 0x0002, "DPAD_DOWN": 0x0004, "DPAD_UP": 0x0008,
           "Z": 0x0010, "R": 0x0020, "L": 0x0040, "A": 0x0100, "B": 0x0200, "X": 0x0400,
           "Y": 0x0800, "START": 0x1000}

# External (character-select) ids, as stored in .slp game start.
CHARACTERS = ["FALCON", "DK", "FOX", "GNW", "KIRBY", "BOWSER", "LINK", "LUIGI", "MARIO", "MARTH",
              "MEWTWO", "NESS", "PEACH", "PIKACHU", "ICS", "PUFF", "SAMUS", "YOSHI", "ZELDA",
              "SHEIK", "FALCO", "YLINK", "DOC", "ROY", "PICHU", "GANON"]

STAGES = {2: "FOUNTAIN", 3: "STADIUM", 8: "YOSHIS", 28: "DREAMLAND", 31: "BATTLEFIELD", 32: "FD"}

RANKS = ["UNKNOWN", "PLATINUM", "DIAMOND", "MASTER", "PRO"]
