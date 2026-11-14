"""See the cube through the wrist camera, grab it and lift it.

    scan   → sweep the table from above until the camera sees a red cube
    hover  → move above it, look again from closer, correct the estimate
    descend→ lower the open jaws around it (the cube sits just off the fixed jaw)
    grip   → close the moving jaw; a jaw that closes all the way means a miss
    lift   → raise it, and check the cube really came along

Postures come from `TITI/voice_motor/kinematics.solve` (the real arm's IK), so
the commands are the same raw ticks the real arm would get. `run()` is a
generator: the caller steps physics and calls next() once per frame.
"""

from __future__ import annotations

import math
from collections.abc import Callable

import numpy as np

from TITI.voice_motor import kinematics as kin

from . import arm, scene
from .eye import WristEye
from .physics_arm import SimArm

SCAN_RADIUS = 0.20
SCAN_HEIGHT = 0.09  # grasp point height while scanning (camera ~0.165 m up)
SCAN_PANS_DEG = (0, 30, -30, 60, -60)
HOVER = 0.06  # above the grasp height
LIFT = 0.08
# The fixed jaw's inner face is 7.9 mm from the grasp axis (kinematics.py);
# park the cube this far off it so a few mm of camera error cannot land the
# fixed jaw on top of the cube.
FIXED_JAW_X = 0.0079
JAW_CLEARANCE = 0.006
GRASP_ABOVE_CENTER = 0.002
MISS_MARGIN = 0.08  # rad: a gripper closer than this to fully shut holds nothing
MOVE_TIMEOUT = 5.0


def heading(v) -> float:
    return math.atan2(v[1], v[0])


def wrap(a: float) -> float:
    return (a + math.pi) % (2 * math.pi) - math.pi


class Picker:
    def __init__(
        self,
        sim: SimArm,
        eye: WristEye,
        limits: dict | None = None,
        log: Callable[[str], None] = print,
    ):
        self.sim, self.eye = sim, eye
        self.m, self.d = sim.m, sim.d
        self.size = scene.cube_size(self.m)
        if limits is None:  # the model's ranges (CAD ∪ measured arm.json)
            limits = {
                mo: tuple(
                    arm.q_to_tick(mo, q) for q in self.m.joint(arm.JOINTS[mo]).range
                )
                for mo in arm.ARM
            }
        self.limits = limits
        roll = self.m.joint("wrist_roll").range
        self.roll_range = (float(roll[0]), float(roll[1]))
        self.log = log
        self.stage, self.status = "idle", ""
        self.result: str | None = None
        self.sighting = None

    # ---- postures ----
    def pose_for(self, target, up_heading: float, yaw: float | None = None) -> dict:
        """motor_1~5 ticks: grasp point at `target`, pointing down, wrist turned so
        the camera's "up" (and the camera itself) faces `up_heading`. With `yaw`
        the jaws close along that heading mod 90° instead (the cube's edges),
        picking the turn that keeps the camera closest to `up_heading`."""
        seed = self.sim.goal_ticks()
        ticks = kin.solve(target, yaw=None, seed=seed, limits=self.limits)
        q = kin.angles(ticks)
        x0 = heading(kin.fk_angles([*q[:4], 0.0])[:3, 0])
        x1 = heading(kin.fk_angles([*q[:4], 0.1])[:3, 0])
        sign = 1.0 if wrap(x1 - x0) > 0 else -1.0
        pose0 = kin.fk_angles([*q[:4], 0.0])
        y_minus_x = wrap(heading(pose0[:3, 1]) - heading(pose0[:3, 0]))
        if yaw is None:
            want_x = [up_heading - y_minus_x]
        else:
            want_x = [yaw + k * math.pi / 2 for k in range(4)]
        best = None
        for wx in want_x:
            for turn in (-2 * math.pi, 0.0, 2 * math.pi):
                roll = sign * wrap(wx - x0) + turn
                if not self.roll_range[0] <= roll <= self.roll_range[1]:
                    continue
                miss = abs(wrap(wx + y_minus_x - up_heading))
                cost = (miss, abs(roll - q[4]))
                if best is None or cost < best[0]:
                    best = (cost, roll)
        roll = best[1] if best else q[4]
        return kin.to_ticks([*q[:4], roll])

    def grasp_pose(self, x, y, yaw, up: float) -> dict:
        """Ticks putting the cube between the jaws, `up` metres above grasp height."""
        out = heading((x, y))
        z = self.size / 2 + GRASP_ABOVE_CENTER + up
        cube_x = FIXED_JAW_X - self.size / 2 - JAW_CLEARANCE  # cube center, grasp frame
        target = np.array([x, y, z])
        ticks = self.pose_for(target, out, yaw)
        for _ in range(2):  # the offset depends on which way the jaws ended up
            closing = kin.fk(ticks)[:3, 0]
            ticks = self.pose_for(np.array([x, y, z]) - cube_x * closing, out, yaw)
        return ticks

    # ---- generator helpers ----
    def say(self, stage: str, message: str) -> None:
        self.stage, self.status = stage, message
        self.log(f"[{stage}] {message}")

    def move(self, ticks: dict, speed: float | None = None):
        deadline = self.d.time + self.sim.command(ticks, speed) + MOVE_TIMEOUT
        while not self.sim.settled() and self.d.time < deadline:
            yield

    def wait(self, seconds: float):
        end = self.d.time + seconds
        while self.d.time < end:
            yield

    def gripper(self, open_: bool, speed=2.0):
        tick = arm.GRIPPER_OPEN_TICK if open_ else arm.GRIPPER_CLOSED_TICK
        travel = self.sim.command({"motor_6": tick}, speed)
        yield from self.wait(travel + (0.2 if open_ else 0.5))

    # ---- the task ----
    def run(self):
        self.result = None
        self.say("scan", "손목 카메라로 큐브를 찾는 중")
        yield from self.gripper(open_=True)
        found = None
        for pan_deg in SCAN_PANS_DEG:
            pan = math.radians(pan_deg)
            look = (
                SCAN_RADIUS * math.cos(pan),
                SCAN_RADIUS * math.sin(pan),
                SCAN_HEIGHT,
            )
            yield from self.move(self.pose_for(look, pan))
            yield from self.wait(0.25)
            found = self.eye.find_cube(self.d, self.size)
            if found:
                break
        if found is None:
            self.result = "not_found"
            self.say("fail", "큐브를 찾지 못했습니다")
            return
        self.sighting = found
        self.say(
            "hover",
            f"큐브 발견: x={found.x * 1000:.0f} y={found.y * 1000:.0f} mm, "
            f"{math.degrees(found.yaw):.0f}°",
        )

        yield from self.move(self.grasp_pose(found.x, found.y, found.yaw, HOVER))
        yield from self.wait(0.25)
        closer = self.eye.find_cube(self.d, self.size)
        if closer:
            found = self.sighting = closer
            self.say(
                "hover",
                f"가까이서 보정: x={found.x * 1000:.0f} y={found.y * 1000:.0f} mm",
            )
            yield from self.move(self.grasp_pose(found.x, found.y, found.yaw, HOVER))

        self.say("descend", "내려가는 중")
        yield from self.move(
            self.grasp_pose(found.x, found.y, found.yaw, 0.0), speed=0.5
        )

        self.say("grip", "잡는 중")
        yield from self.gripper(open_=False, speed=1.5)
        closed_q = arm.tick_to_q("motor_6", arm.GRIPPER_CLOSED_TICK)
        if self.sim.gripper_q() < closed_q + MISS_MARGIN:
            self.result = "missed"
            self.say("fail", "집게가 끝까지 닫혔습니다 (큐브를 놓침)")
            yield from self.gripper(open_=True)
            yield from self.move(self.grasp_pose(found.x, found.y, found.yaw, HOVER))
            return

        self.say("lift", "들어 올리는 중")
        yield from self.move(
            self.grasp_pose(found.x, found.y, found.yaw, LIFT), speed=0.6
        )
        yield from self.wait(0.8)
        lifted = scene.cube_pose(self.m, self.d)[0][2] - self.size / 2
        if lifted > LIFT * 0.6:
            self.result = "lifted"
            self.say("done", f"성공: 큐브를 {lifted * 1000:.0f} mm 들어 올렸습니다")
        else:
            self.result = "dropped"
            self.say("fail", f"큐브가 따라오지 않았습니다 ({lifted * 1000:.0f} mm)")

    def put_back(self):
        """Lower the held cube to the table, release it, and back off."""
        if self.sighting is None:
            return
        s = self.sighting
        self.say("place", "내려놓는 중")
        yield from self.move(self.grasp_pose(s.x, s.y, s.yaw, 0.003), speed=0.6)
        yield from self.gripper(open_=True)
        yield from self.move(self.grasp_pose(s.x, s.y, s.yaw, HOVER))
