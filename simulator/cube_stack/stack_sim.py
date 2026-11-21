"""Stack red, yellow and blue cubes with the SO-101 in MuJoCo (OpenCV only).

    mjpython simulator/cube_stack/stack_sim.py                 # window, endless
    mjpython simulator/cube_stack/stack_sim.py --once --seed 3
    python   simulator/cube_stack/stack_sim.py --headless --sheet stack.png
    python   simulator/cube_stack/stack_sim.py --headless --trials 50

Window: the third-person view; insets show the fixed camera and the wrist
camera with what the detector found. [ / ] cycle cameras, Tab shows the UI.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import cv2
import mujoco
import numpy as np

HERE = Path(__file__).resolve().parent
for _p in (HERE, HERE.parent, HERE.parents[1]):  # stack/, sim/, TITI/
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
from sim import arm
from sim.physics_arm import SimArm
from sim.world import START
from stack import referee, scene
from stack.eye import FixedEye, WristEye
from stack.stacker import Stacker

FPS = 60
STAGE_TEXT = {
    "calibrate": "Learning where the jaws show up",
    "look": "Fixed camera: mapping the cubes",
    "pick": "Picking",
    "place": "Placing on the tower",
    "check": "Checking the tower",
    "retry": "Starting over",
    "final": "Final check",
    "done": "Stacked!",
    "fail": "Failed",
    "idle": "",
}


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="SO-101 three-cube stacking (MuJoCo + OpenCV)"
    )
    p.add_argument("--once", action="store_true", help="one stack, then stay")
    p.add_argument("--seed", type=int, default=None, help="random layout seed")
    p.add_argument("--order", default="red,yellow,blue", help="bottom → top")
    p.add_argument("--speed", type=float, default=1.0, help="playback speed")
    p.add_argument("--headless", action="store_true", help="no window")
    p.add_argument(
        "--sheet", metavar="PNG", help="headless: stage-by-stage contact sheet"
    )
    p.add_argument("--trials", type=int, default=1, help="headless: layouts to run")
    p.add_argument("--quiet", action="store_true", help="headless: only the results")
    p.add_argument("--profile", default=str(arm.DEFAULT_PROFILE))
    return p.parse_args(argv)


class Episode:
    def __init__(self, args, log=print):
        self.args = args
        self.order = tuple(c.strip() for c in args.order.split(","))
        if sorted(self.order) != sorted(scene.COLORS):
            raise SystemExit(f"--order must list {', '.join(scene.COLORS)} once each")
        self.m = scene.build_model(arm.load_profile(args.profile))
        self.d = mujoco.MjData(self.m)
        self.sim = SimArm(self.m, self.d)
        self.wrist = WristEye(self.m)
        self.top = FixedEye(self.m)
        self.stacker = Stacker(
            self.sim, self.wrist, self.top, scene.cube_size(self.m), self.order, log
        )
        self.rng = np.random.default_rng(args.seed)
        self.grades: list[dict] = []
        self.new_layout()

    def new_layout(self):
        mujoco.mj_resetData(self.m, self.d)
        self.sim = self.stacker.sim = SimArm(self.m, self.d)
        self.stacker.d = self.d
        self.wrist.gripper_q = self.sim.gripper_q
        self.sim.reset_to(START)
        self.layout = scene.random_layout(self.rng)
        scene.place_layout(self.m, self.d, self.layout)
        self.t0 = self.d.time

    def cycle(self):
        while True:
            yield from self.stacker.run()
            yield from self.stacker.wait(2.0)  # the tower must stand still
            g = referee.grade(self.m, self.d, self.order)
            g.update(claim=self.stacker.result, seconds=self.d.time - self.t0)
            self.grades.append(g)
            print(summary(g))
            if self.args.once:
                return
            self.new_layout()

    def close(self):
        self.wrist.close()
        self.top.close()


def summary(g: dict) -> str:
    layers = " ".join(
        f"{L['color']}[{L['offset_mm']:.1f}mm {L['yaw_deg']:.0f}°{'' if L['ok'] else ' ✗'}]"
        for L in g["layers"]
    )
    verdict = "STACKED" if g["stacked"] else "NOT STACKED"
    return f"referee: {verdict} | stacker said: {g['claim']} | {g['seconds']:.0f}s | {layers}"


def run_headless(ep: Episode) -> None:
    sheet, last = [], None
    third = mujoco.Renderer(ep.m, 300, 400) if ep.args.sheet else None

    def grab():
        third.update_scene(ep.d, "overview")
        top = cv2.resize(ep.top.capture(ep.d), (400, 300))
        sheet.append(np.concatenate([third.render(), top], 0))

    steps = ep.cycle()
    for _ in steps:
        ep.sim.step(1 / FPS)
        if third and ep.stacker.stage != last:
            last = ep.stacker.stage
            grab()
    if third:
        grab()
        rows = [np.concatenate(sheet[i : i + 8], 1) for i in range(0, len(sheet), 8)]
        w = max(r.shape[1] for r in rows)
        rows = [np.pad(r, ((0, 0), (0, w - r.shape[1]), (0, 0))) for r in rows]
        cv2.imwrite(
            ep.args.sheet, cv2.cvtColor(np.concatenate(rows, 0), cv2.COLOR_RGB2BGR)
        )
        print(f"saved {ep.args.sheet}")


def run_viewer(ep: Episode) -> None:
    import mujoco.viewer

    with mujoco.viewer.launch_passive(
        ep.m, ep.d, show_left_ui=False, show_right_ui=False
    ) as viewer:
        viewer.cam.type = mujoco.mjtCamera.mjCAMERA_FIXED
        viewer.cam.fixedcamid = ep.m.camera("overview").id
        steps = ep.cycle()
        frame, top_view = 0, None
        while viewer.is_running():
            begin = time.monotonic()
            with viewer.lock():
                ep.sim.step(ep.args.speed / FPS)
                try:
                    next(steps)
                except StopIteration:
                    pass
                if frame % 3 == 0:
                    top_view = ep.top.last_view
                    if top_view is None or ep.stacker.stage not in ("look", "final"):
                        top_view = ep.top.capture(ep.d)
            frame += 1
            ok = sum(g["stacked"] for g in ep.grades)
            viewer.set_texts(
                (
                    mujoco.mjtFontScale.mjFONTSCALE_150,
                    mujoco.mjtGridPos.mjGRID_TOPLEFT,
                    STAGE_TEXT.get(ep.stacker.stage, ep.stacker.stage),
                    f"stacks: {ok}/{len(ep.grades)}",
                )
            )
            vp = viewer.viewport
            if vp is not None and vp.width > 400:
                images = [
                    (
                        mujoco.MjrRect(vp.width - 330, 10, 320, 240),
                        cv2.resize(top_view, (320, 240), interpolation=cv2.INTER_AREA),
                    )
                ]
                wrist = ep.wrist.last_view
                if wrist is not None:
                    images.append(
                        (
                            mujoco.MjrRect(vp.width - 330, 260, 320, 240),
                            cv2.resize(wrist, (320, 240), interpolation=cv2.INTER_AREA),
                        )
                    )
                viewer.set_images(images)
            viewer.sync()
            time.sleep(max(0.0, 1 / FPS - (time.monotonic() - begin)))


def main(argv=None) -> int:
    args = parse_args(argv)
    log = (lambda _m: None) if args.quiet else print
    ep = Episode(args, log)
    try:
        if args.headless or args.sheet:
            args.once = True
            for i in range(args.trials):
                if i:
                    ep.new_layout()
                run_headless(ep)
            if args.trials > 1:
                ok = sum(g["stacked"] for g in ep.grades)
                lies = sum((g["claim"] == "stacked") != g["stacked"] for g in ep.grades)
                print(f"\n{ok}/{args.trials} stacked, wrong self-verdicts: {lies}")
        else:
            run_viewer(ep)
    finally:
        ep.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
