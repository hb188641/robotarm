"""Show the real SO-101 live in a MuJoCo window (read-only mirror).

Polls robot_arm_app's GET /api/state and poses the model to match. Nothing is
ever sent to the arm. On macOS the viewer must run under `mjpython`:

    mjpython simulator/mirror.py                         # http://localhost:6000
    mjpython simulator/mirror.py --base-url http://192.168.0.10:6000 --hz 10
    mjpython simulator/mirror.py --demo                  # no hardware: taught poses
    python   simulator/mirror.py --demo --snapshot out.png   # one offscreen frame
"""

from __future__ import annotations

import argparse
import math
import sys
import time
from pathlib import Path

import mujoco
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sim import arm
from sim.sources import DemoSource, HttpSource

FPS = 60
SMOOTH_S = 0.06  # time constant easing the model toward each new sample


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="MuJoCo mirror of the real SO-101 arm")
    p.add_argument("--base-url", default="http://localhost:6000")
    p.add_argument("--hz", type=float, default=15.0, help="/api/state polling rate")
    p.add_argument("--demo", action="store_true", help="cycle taught poses, no server")
    p.add_argument(
        "--profile",
        default=str(arm.DEFAULT_PROFILE),
        help="arm.json with measured limits",
    )
    p.add_argument(
        "--snapshot", metavar="PNG", help="render one frame offscreen and exit"
    )
    return p.parse_args(argv)


def target_qpos(model, ticks: dict) -> np.ndarray:
    data = mujoco.MjData(model)
    arm.set_ticks(model, data, ticks)
    return data.qpos.copy()


def overlay(status: str, ticks: dict | None):
    rows = "\n".join(f"{m}" for m in arm.MOTORS)
    vals = "\n".join(str(ticks[m]) if ticks and m in ticks else "-" for m in arm.MOTORS)
    return [
        (
            mujoco.mjtFontScale.mjFONTSCALE_150,
            mujoco.mjtGridPos.mjGRID_TOPLEFT,
            status,
            "",
        ),
        (
            mujoco.mjtFontScale.mjFONTSCALE_150,
            mujoco.mjtGridPos.mjGRID_BOTTOMLEFT,
            rows,
            vals,
        ),
    ]


def snapshot(model, source, path: str, wait_s: float = 3.0) -> None:
    deadline = time.monotonic() + wait_s
    ticks, status = source.latest()
    while ticks is None and time.monotonic() < deadline:
        time.sleep(0.05)
        ticks, status = source.latest()
    data = mujoco.MjData(model)
    if ticks:
        arm.set_ticks(model, data, ticks)
    mujoco.mj_forward(model, data)
    cam = mujoco.MjvCamera()
    cam.lookat[:] = [0.12, 0.0, 0.14]
    cam.distance, cam.azimuth, cam.elevation = 0.75, 135, -22
    with mujoco.Renderer(model, 600, 800) as r:
        r.update_scene(data, cam)
        image = r.render()
    from PIL import Image

    Image.fromarray(image).save(path)
    print(f"{status}\nsaved {path}")


def run_viewer(model, source) -> None:
    import mujoco.viewer

    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    first = True
    with mujoco.viewer.launch_passive(model, data) as viewer:
        viewer.opt.sitegroup[arm.GRASP_SITE_GROUP] = 1  # show the grasp point
        last = time.monotonic()
        while viewer.is_running():
            now = time.monotonic()
            dt, last = now - last, now
            ticks, status = source.latest()
            with viewer.lock():
                if ticks:
                    goal = target_qpos(model, {**arm.get_ticks(model, data), **ticks})
                    k = 1.0 if first else 1 - math.exp(-dt / SMOOTH_S)
                    data.qpos[:] += (goal - data.qpos) * k
                    first = False
                mujoco.mj_forward(model, data)
            viewer.set_texts(overlay(status, ticks))
            viewer.sync()
            time.sleep(max(0.0, 1 / FPS - (time.monotonic() - now)))


def main(argv=None) -> None:
    args = parse_args(argv)
    model = arm.build_model(arm.load_profile(args.profile))
    source = DemoSource() if args.demo else HttpSource(args.base_url, args.hz).start()
    try:
        if args.snapshot:
            snapshot(model, source, args.snapshot)
        else:
            run_viewer(model, source)
    finally:
        if isinstance(source, HttpSource):
            source.stop()


if __name__ == "__main__":
    main()
