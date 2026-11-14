"""First-person cube pick in MuJoCo: find the red cube, grab it, lift it.

The main window is the wrist camera (the robot's own view). Insets show what
the cube detector saw (green outline) and a third-person view of the arm.
After each pick the cube is put back down and a new one appears elsewhere.

    mjpython simulator/pick_sim.py                    # endless, real time
    mjpython simulator/pick_sim.py --once --cube 0.22 0.05 20
    python   simulator/pick_sim.py --headless --sheet pick.png   # no window

In the window: [ / ] cycle cameras (Esc = free camera), Tab shows the UI.
"""

from __future__ import annotations

import argparse
import math
import sys
import time
from pathlib import Path

import cv2
import mujoco
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sim import arm, scene
from sim.eye import WristEye
from sim.physics_arm import SimArm
from sim.picker import Picker
from sim.world import START

FPS = 60
STAGE_TEXT = {
    "scan": "Looking for the red cube",
    "hover": "Cube found - moving above it",
    "descend": "Lowering the open jaws",
    "grip": "Closing the gripper",
    "lift": "Lifting",
    "done": "Lifted!",
    "fail": "Failed",
    "place": "Putting it back",
    "idle": "",
}


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="SO-101 first-person cube pick (MuJoCo)")
    p.add_argument("--once", action="store_true", help="one pick, then stay")
    p.add_argument(
        "--cube",
        nargs=3,
        type=float,
        metavar=("X", "Y", "YAW_DEG"),
        help="cube spot in m/m/deg (default: random)",
    )
    p.add_argument("--seed", type=int, default=None, help="random cube spots seed")
    p.add_argument(
        "--speed", type=float, default=1.0, help="playback speed vs real time"
    )
    p.add_argument(
        "--headless", action="store_true", help="no window; print the result"
    )
    p.add_argument(
        "--sheet", metavar="PNG", help="headless: save a stage-by-stage contact sheet"
    )
    p.add_argument("--profile", default=str(arm.DEFAULT_PROFILE))
    return p.parse_args(argv)


class Episode:
    """One scene: model, physics, eye and picker, plus the endless cycle."""

    def __init__(self, args):
        self.args = args
        self.m = scene.build_pick_model(arm.load_profile(args.profile))
        self.d = mujoco.MjData(self.m)
        self.sim = SimArm(self.m, self.d)
        self.eye = WristEye(self.m)
        self.picker = Picker(self.sim, self.eye)
        self.rng = np.random.default_rng(args.seed)
        self.results: list[str] = []
        self.sim.reset_to(START)
        self.new_cube(args.cube)

    def new_cube(self, spot=None):
        if spot:
            x, y, yaw = spot[0], spot[1], math.radians(spot[2])
        else:
            x, y, yaw = scene.random_cube_spot(self.rng)
        scene.place_cube(self.m, self.d, x, y, yaw)
        mujoco.mj_forward(self.m, self.d)
        print(
            f"\n새 큐브: x={x * 1000:.0f} y={y * 1000:.0f} mm, {math.degrees(yaw):.0f}°"
        )

    def cycle(self):
        """Pick → hold → put back → new cube, forever (or once with --once)."""
        while True:
            yield from self.picker.run()
            self.results.append(self.picker.result)
            yield from self.picker.wait(1.5)
            if self.args.once:
                return
            if self.picker.result == "lifted":
                yield from self.picker.put_back()
            yield from self.picker.wait(0.5)
            self.new_cube()


def run_headless(ep: Episode) -> None:
    sheet = []
    overview = mujoco.Renderer(ep.m, 300, 400) if ep.args.sheet else None
    last = None

    def grab():
        from PIL import Image

        wrist = np.array(Image.fromarray(ep.eye.capture(ep.d)).resize((400, 300)))
        overview.update_scene(ep.d, "overview")
        sheet.append(np.concatenate([wrist, overview.render()], 0))

    for _ in ep.cycle():
        ep.sim.step(1 / FPS)
        if overview and ep.picker.stage != last:
            last = ep.picker.stage
            grab()
    if overview:
        grab()
        from PIL import Image

        Image.fromarray(np.concatenate(sheet, 1)).save(ep.args.sheet)
        print(f"saved {ep.args.sheet}")
    print(f"result: {ep.picker.result}")


def run_viewer(ep: Episode) -> None:
    import mujoco.viewer

    third = mujoco.Renderer(ep.m, 240, 320)
    with mujoco.viewer.launch_passive(
        ep.m, ep.d, show_left_ui=False, show_right_ui=False
    ) as viewer:
        viewer.cam.type = mujoco.mjtCamera.mjCAMERA_FIXED
        viewer.cam.fixedcamid = ep.m.camera("wrist").id
        steps = ep.cycle()
        frame = 0
        while viewer.is_running():
            begin = time.monotonic()
            with viewer.lock():
                ep.sim.step(ep.args.speed / FPS)
                try:
                    next(steps)
                except StopIteration:
                    pass
                if frame % 2 == 0:
                    third.update_scene(ep.d, "overview")
                    inset_third = third.render()
            frame += 1
            viewer.set_texts(
                (
                    mujoco.mjtFontScale.mjFONTSCALE_150,
                    mujoco.mjtGridPos.mjGRID_TOPLEFT,
                    STAGE_TEXT.get(ep.picker.stage, ep.picker.stage),
                    f"picks: {ep.results.count('lifted')}/{len(ep.results)}",
                )
            )
            vp = viewer.viewport
            if vp is not None and vp.width > 400:
                images = [(mujoco.MjrRect(vp.width - 330, 10, 320, 240), inset_third)]
                if ep.eye.last_view is not None:  # what the detector last saw
                    seen = cv2.resize(
                        ep.eye.last_view, (320, 240), interpolation=cv2.INTER_AREA
                    )
                    images.append((mujoco.MjrRect(vp.width - 330, 260, 320, 240), seen))
                viewer.set_images(images)
            viewer.sync()
            time.sleep(max(0.0, 1 / FPS - (time.monotonic() - begin)))


def main(argv=None) -> None:
    args = parse_args(argv)
    ep = Episode(args)
    try:
        if args.headless or args.sheet:
            args.once = True
            run_headless(ep)
        else:
            run_viewer(ep)
    finally:
        ep.eye.close()


if __name__ == "__main__":
    main()
