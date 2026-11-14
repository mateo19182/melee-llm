"""Screenshots of a rendered game for vision-capable LLM players.

Each rendered game runs on its own private Xvfb display (`PrivateDisplay`), so parallel games never see each
other's windows. `Camera` finds Dolphin's game window (title contains GALE01, like scripts/stream.sh) and
grabs it through XCB (Pillow's ImageGrab), downscaled and JPEG-encoded for the prompt.

    with PrivateDisplay() as disp:          # sets $DISPLAY for the Dolphin that play() starts
        play(agents, iso, mode="paused")    # agents with obs=image|both build a Camera on $DISPLAY

Measured on the shared 3090 host (2026-11-14): see docs/perception.md.
"""
from __future__ import annotations

import base64
import io
import os
import re
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageGrab

SCREEN = (1280, 960)


class PrivateDisplay:
    """An Xvfb display of our own (first free number from `first`), for one rendered game.

    Free numbers are claimed by Xvfb's own lock file, so parallel callers that race for a number just retry
    the next one. `set_env` points $DISPLAY at it while open (restored on close).
    """

    def __init__(self, first: int = 120, last: int = 199, size: tuple[int, int] = SCREEN, set_env: bool = True):
        self.first, self.last, self.size, self.set_env = first, last, size, set_env
        self.proc: subprocess.Popen | None = None
        self.name = ""
        self._old_env: str | None = None

    def start(self) -> str:
        for n in range(self.first, self.last + 1):
            if Path(f"/tmp/.X{n}-lock").exists() or Path(f"/tmp/.X11-unix/X{n}").exists():
                continue
            p = subprocess.Popen(["Xvfb", f":{n}", "-screen", "0", f"{self.size[0]}x{self.size[1]}x24", "-nolisten", "tcp"],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=False)
            for _ in range(50):
                if p.poll() is not None:
                    break  # lost the race for this number (or it was taken): try the next
                if Path(f"/tmp/.X11-unix/X{n}").exists():
                    self.proc, self.name = p, f":{n}"
                    if self.set_env:
                        self._old_env = os.environ.get("DISPLAY")
                        os.environ["DISPLAY"] = self.name
                    return self.name
                time.sleep(0.05)
            p.kill()
        raise RuntimeError(f"no free X display in :{self.first}-:{self.last}")

    def stop(self) -> None:
        if self.proc:
            self.proc.terminate()
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
            self.proc = None
        if self.set_env and self.name:
            if self._old_env is None:
                os.environ.pop("DISPLAY", None)
            else:
                os.environ["DISPLAY"] = self._old_env

    def __enter__(self) -> "PrivateDisplay":
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.stop()


_GEOM = re.compile(r'"[^"]*GALE01[^"]*".*?(\d+)x(\d+)\+-?\d+\+-?\d+\s+\+(-?\d+)\+(-?\d+)')


def find_game_window(display: str) -> tuple[int, int, int, int] | None:
    """(x, y, w, h) of Dolphin's render window on `display`, or None while it is not up yet."""
    try:
        out = subprocess.run(["xwininfo", "-root", "-tree"], env={**os.environ, "DISPLAY": display},
                             capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    best = None
    for m in _GEOM.finditer(out):
        w, h, x, y = map(int, m.groups())
        if w > 100 and h > 100 and (best is None or w * h > best[2] * best[3]):
            best = (x, y, w, h)
    return best


@dataclass
class Shot:
    """One frame as sent to the model: JPEG bytes plus where it came from."""
    jpeg: bytes
    frame: int  # game frame when grabbed (paused: exact; live: the frame step() was on)
    size: tuple[int, int]
    grab_ms: float
    encode_ms: float
    t: float = field(default_factory=time.time)

    def data_uri(self) -> str:
        return "data:image/jpeg;base64," + base64.b64encode(self.jpeg).decode()

    def claude_tokens(self) -> int:
        """Anthropic's estimate for an image under the size cap: width * height / 750."""
        return round(self.size[0] * self.size[1] / 750)


class Camera:
    """Grabs Dolphin's game window on one X display. `width` is the downscaled width sent to the model."""

    def __init__(self, display: str | None = None, width: int = 512, quality: int = 80):
        self.display = display or os.environ.get("DISPLAY", "")
        self.width, self.quality = width, quality
        self.window: tuple[int, int, int, int] | None = None
        self.ring: deque[Shot] = deque(maxlen=8)
        self.grab_ms: list[float] = []
        self._lock = threading.Lock()  # one grab at a time (live: ring thread + decision thread)
        self._ring_stop: threading.Event | None = None

    def _locate(self) -> bool:
        if self.window is None:
            self.window = find_game_window(self.display)
        return self.window is not None

    def grab_image(self) -> Image.Image | None:
        if not self._locate():
            return None
        x, y, w, h = self.window
        try:
            return ImageGrab.grab(bbox=(x, y, x + w, y + h), xdisplay=self.display)
        except OSError:
            self.window = None  # window moved or display gone; look again next time
            return None

    def shot(self, frame: int) -> Shot | None:
        t0 = time.perf_counter()
        with self._lock:
            img = self.grab_image()
        if img is None:
            return None
        t1 = time.perf_counter()
        if img.width > self.width:
            img = img.resize((self.width, round(img.height * self.width / img.width)), Image.BILINEAR)
        buf = io.BytesIO()
        img.convert("RGB").save(buf, "JPEG", quality=self.quality)
        t2 = time.perf_counter()
        s = Shot(buf.getvalue(), int(frame), img.size, round((t1 - t0) * 1e3, 2), round((t2 - t1) * 1e3, 2))
        self.grab_ms.append(s.grab_ms + s.encode_ms)
        return s

    def tick(self, frame: int, every: int) -> None:
        """Keep a ring of recent frames for clips: call every game frame; grabs every `every` frames."""
        if frame % every == 0:
            s = self.shot(frame)
            if s:
                self.ring.append(s)

    def clip(self, frame: int, n: int, every: int) -> list[Shot]:
        """`n` frames ending now, oldest first: the current frame plus n-1 ring frames spaced `every` apart."""
        now = self.shot(frame)
        if now is None:
            return []
        if n <= 1:
            return [now]
        older = [s for s in list(self.ring) if frame - every * (n - 1) - 2 <= s.frame < frame]
        return (older[-(n - 1):] if older else []) + [now]

    @property
    def ring_running(self) -> bool:
        return self._ring_stop is not None

    def start_ring(self, frame_fn, period_s: float) -> None:
        """Real-time games: fill the clip ring from a thread every `period_s`, labelled with frame_fn()."""
        self._ring_stop = stop = threading.Event()

        def loop():
            while not stop.wait(period_s):
                s = self.shot(frame_fn())
                if s:
                    self.ring.append(s)
        threading.Thread(target=loop, daemon=True, name="camera-ring").start()

    def stop_ring(self) -> None:
        if self._ring_stop:
            self._ring_stop.set()
