"""Where the mirrored arm pose comes from.

Every source has `latest() -> (ticks | None, status)`; ticks is a
{motor_1..motor_6: raw tick} dict, status a short ASCII line for the overlay.

    HttpSource   polls robot_arm_app's GET /api/state in a background thread
    DemoSource   walks through taught poses (poses.json) without any hardware
"""

from __future__ import annotations

import json
import threading
import time
import urllib.request
from pathlib import Path

from .arm import MOTORS, REPO

POSES_JSON = REPO / "TITI" / "voice_motor" / "poses.json"


def fetch_state(base_url: str, timeout: float = 1.0) -> dict[str, int]:
    with urllib.request.urlopen(
        f"{base_url.rstrip('/')}/api/state", timeout=timeout
    ) as r:
        data = json.loads(r.read().decode("utf-8"))
    return {m: int(data[m]) for m in MOTORS if m in data}


class HttpSource:
    """Polls GET /api/state at `hz`. Each poll is one sync_read on the servo bus,
    shared (under app.py's bus lock) with whatever is commanding the arm, so keep
    the rate modest; the viewer smooths between samples."""

    def __init__(self, base_url: str, hz: float = 15.0, fetch=fetch_state):
        self.base_url = base_url
        self.period = 1.0 / hz
        self._fetch = fetch
        self._lock = threading.Lock()
        self._ticks: dict | None = None
        self._status = f"connecting {base_url}"
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> HttpSource:
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()

    def poll_once(self) -> None:
        start = time.monotonic()
        try:
            ticks = self._fetch(self.base_url)
        except (OSError, ValueError, TypeError) as exc:  # URLError, timeout, bad JSON
            with self._lock:
                self._status = f"OFFLINE {self.base_url}: {type(exc).__name__}"
            return
        ms = (time.monotonic() - start) * 1000
        with self._lock:
            self._ticks = ticks
            self._status = f"LIVE {self.base_url}  ({ms:.0f} ms)"

    def _run(self) -> None:
        while not self._stop.is_set():
            begin = time.monotonic()
            self.poll_once()
            self._stop.wait(max(0.0, self.period - (time.monotonic() - begin)))

    def latest(self):
        with self._lock:
            return (dict(self._ticks) if self._ticks else None), self._status


class DemoSource:
    """Cycles through named poses: `move_s` to travel, `hold_s` to rest."""

    def __init__(
        self,
        poses: dict[str, dict] | None = None,
        move_s=2.0,
        hold_s=1.0,
        clock=time.monotonic,
    ):
        if poses is None:
            poses = json.loads(Path(POSES_JSON).read_text(encoding="utf-8"))
        self.names = list(poses)
        self.poses = [{m: p.get(m, 2048) for m in MOTORS} for p in poses.values()]
        self.move_s, self.hold_s = move_s, hold_s
        self._clock = clock
        self._t0 = clock()

    def latest(self):
        span = self.move_s + self.hold_s
        t = self._clock() - self._t0
        i = int(t // span) % len(self.poses)
        a, b = self.poses[i - 1], self.poses[i]
        frac = min((t % span) / self.move_s, 1.0)
        frac = frac * frac * (3 - 2 * frac)  # smoothstep
        ticks = {m: round(a[m] + (b[m] - a[m]) * frac) for m in MOTORS}
        return ticks, f"DEMO -> pose {i + 1}/{len(self.poses)}"
