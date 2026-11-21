"""Stack the three cubes: look, pick, place, check — rules only, no learning.

    calibrate → arm straight up (camera at the sky): learn where the jaws show
    look      → arm parked, the fixed camera maps all three cubes
    for each cube after the base:
        pick  → hover, correct with the wrist camera, descend, grip, lift, check
        place → over the tower, lower, release, back off
        check → wrist camera over the tower: the new top is the right color, centered
    final     → park and check the whole tower with the fixed camera

Decisions use only what the real arm could know: the two cameras, the joint
positions and the gripper load. The cubes' true poses are for the referee.
`run()` is a generator; the caller steps physics and calls next() each frame.
"""

from __future__ import annotations

import math
from collections.abc import Callable

import numpy as np
from sim import arm
from sim.picker import (
    FIXED_JAW_X,
    GRASP_ABOVE_CENTER,
    HOLD_FORCE,
    JAW_CLEARANCE,
    MIN_RED_PIXELS,
    MISS_MARGIN,
    SAME_VIEW,
    Picker,
    heading,
)
from sim.world import START

from TITI.voice_motor import kinematics as kin

from .eye import FixedEye, WristEye, overlap
from .scene import COLORS

# Arm straight up: out of the fixed camera's work area, wrist camera at the sky.
PARK = {**START, "motor_2": 1700, "motor_3": 1300, "motor_4": 2048, "motor_5": 2048}
HOVER = 0.06  # above the grasp height (pick) or the tower top (place)
LIFT = 0.10
PLACE_GAP = 0.002  # release the cube this far above the tower top
ALIGN_TOL = 0.006  # m: a placed cube this far off the one below is a failure
SIDE_TOL = 0.025  # m: a lower cube's side face seen by the fixed camera
WRIST_AGREE = 0.015  # m: a wrist correction further than this from the map is ignored
PICK_TRIES = 3
RESTARTS = 2


class Stacker(Picker):
    def __init__(
        self,
        sim,
        wrist: WristEye,
        top: FixedEye,
        size: float,
        order=COLORS,
        log: Callable[[str], None] = print,
    ):
        # Picker's helpers (pose_for, move, wait, gripper, jaw_gap) without its
        # single-red-cube setup.
        self.sim, self.eye, self.top = sim, wrist, top
        self.m, self.d = sim.m, sim.d
        self.size = size
        self.order = tuple(order)
        self.limits = {
            mo: tuple(arm.q_to_tick(mo, q) for q in self.m.joint(arm.JOINTS[mo]).range)
            for mo in arm.ARM
        }
        roll = self.m.joint("wrist_roll").range
        self.roll_range = (float(roll[0]), float(roll[1]))
        self.log = log
        self.stage, self.status = "idle", ""
        self.result: str | None = None
        self.sighting = None
        self.map: dict = {}  # color → Sighting (table plane)
        self.tower = None  # (x, y, yaw) of the current top
        self.height = 0  # cubes in the tower
        self.claims: list[str] = []  # what the stacker believes, for the referee
        wrist.gripper_q = sim.gripper_q

    # ---- poses ----
    def jaw_pose(self, x, y, yaw, center_z, cube_x) -> dict:
        """Ticks putting a cube center at (x, y, center_z) with the jaws along `yaw`,
        the cube `cube_x` off the grasp axis toward the fixed jaw."""
        z = center_z + GRASP_ABOVE_CENTER
        out = heading((x, y))
        ticks = self.pose_for(np.array([x, y, z]), out, yaw)
        for _ in range(2):
            closing = kin.fk(ticks)[:3, 0]
            ticks = self.pose_for(np.array([x, y, z]) - cube_x * closing, out, yaw)
        return ticks

    def open_pose(self, x, y, yaw, level, up) -> dict:
        """Open jaws around a cube resting on `level` cubes, `up` above it."""
        cube_x = FIXED_JAW_X - self.size / 2 - JAW_CLEARANCE
        return self.jaw_pose(x, y, yaw, (level + 0.5) * self.size + up, cube_x)

    def held_pose(self, x, y, yaw, level, up) -> dict:
        """The held cube (pressed on the fixed jaw) over `level` cubes, `up` above."""
        cube_x = FIXED_JAW_X - self.size / 2
        return self.jaw_pose(x, y, yaw, (level + 0.5) * self.size + up, cube_x)

    def plane(self, level) -> float:
        return (level + 0.5) * self.size

    # ---- steps ----
    def calibrate(self):
        self.say("calibrate", "집게가 카메라에 보이는 곳을 익히는 중 (하늘을 봄)")
        yield from self.move(PARK)
        self.eye.jaw_masks.clear()
        for tick in (arm.GRIPPER_OPEN_TICK, 2200, 1900, arm.GRIPPER_CLOSED_TICK):
            yield from self.wait(self.sim.command({"motor_6": tick}, 2.0) + 0.3)
            self.eye.learn_jaws(self.d, self.sim.gripper_q())
        yield from self.gripper(open_=True)

    def look(self):
        """Park and map all cubes with the fixed camera."""
        self.say("look", "팔을 치우고 고정 카메라로 큐브를 찾는 중")
        yield from self.move(PARK)
        yield from self.wait(0.3)
        self.map = self.top.find_all(self.d, self.plane(0))
        seen = ", ".join(
            f"{c} ({s.x * 1000:.0f}, {s.y * 1000:.0f}) mm" for c, s in self.map.items()
        )
        self.say("look", f"찾음: {seen or '없음'}")
        yield from self.move(START)

    def hover_look(self, color, level, guess, pose):
        """Move to `pose` and read `color` with the wrist camera near `guess`."""
        yield from self.move(pose)
        yield from self.wait(0.2)
        s = self.eye.look(self.d, color, self.plane(level), near=(*guess, WRIST_AGREE))
        return s

    def pick(self, color):
        s = self.map[color]
        self.say("pick", f"{color} 큐브 위로")
        closer = yield from self.hover_look(
            color, 0, (s.x, s.y), self.open_pose(s.x, s.y, s.yaw, 0, HOVER)
        )
        if closer:
            s = closer
            yield from self.move(self.open_pose(s.x, s.y, s.yaw, 0, HOVER))
        self.say("pick", f"{color} 내려가서 잡기")
        yield from self.move(self.open_pose(s.x, s.y, s.yaw, 0, 0.0), speed=0.5)
        yield from self.gripper(open_=False, speed=1.5)
        if self.jaw_gap() < MISS_MARGIN:
            self.say("pick", "집게가 끝까지 닫힘: 놓침")
            yield from self.gripper(open_=True)
            yield from self.move(self.open_pose(s.x, s.y, s.yaw, 0, HOVER))
            return False
        in_hand = self.eye.color_pixels(self.d, color)
        yield from self.move(self.open_pose(s.x, s.y, s.yaw, 0, LIFT), speed=0.6)
        yield from self.wait(0.5)
        force = abs(self.sim.gripper_force())
        ok = self.jaw_gap() >= MISS_MARGIN and force >= HOLD_FORCE
        if in_hand.sum() >= MIN_RED_PIXELS:
            ok = (
                ok
                and overlap(in_hand, self.eye.color_pixels(self.d, color)) >= SAME_VIEW
            )
        if not ok:
            self.say("pick", f"{color} 큐브가 따라오지 않음")
            yield from self.gripper(open_=True)
        return ok

    def place(self, color):
        x, y, yaw = self.tower
        level = self.height
        self.say("place", f"{color} 큐브를 {level + 1}층에 올리는 중")
        yield from self.move(self.held_pose(x, y, yaw, level, HOVER + 0.02))
        yield from self.move(self.held_pose(x, y, yaw, level, HOVER), speed=0.6)
        yield from self.move(self.held_pose(x, y, yaw, level, PLACE_GAP), speed=0.3)
        yield from self.wait(0.3)
        yield from self.gripper(open_=True, speed=0.8)
        yield from self.wait(0.3)
        yield from self.move(self.held_pose(x, y, yaw, level, HOVER), speed=0.5)

    def check_top(self, color, level):
        """Wrist camera over the tower: is `color` now on top, on center?"""
        x, y, yaw = self.tower
        s = yield from self.hover_look(
            color, level, (x, y), self.open_pose(x, y, yaw, level, HOVER)
        )
        if s is None:
            self.say("check", f"탑 위에서 {color}이(가) 보이지 않음")
            return None
        off = math.hypot(s.x - x, s.y - y)
        self.say(
            "check", f"{level + 1}층 {color}: 아래 큐브와 {off * 1000:.1f} mm 차이"
        )
        return s if off <= ALIGN_TOL else None

    def run(self):
        self.result = None
        self.claims = []
        yield from self.gripper(open_=True)
        yield from self.calibrate()
        for attempt in range(RESTARTS + 1):
            done = yield from self.build()
            if done:
                break
            if attempt < RESTARTS:
                self.say("retry", "처음부터 다시 봅니다")
        yield from self.final_check()

    def build(self):
        yield from self.look()
        missing = [c for c in self.order if c not in self.map]
        base = self.order[0]
        if base in missing:
            self.say("fail", f"바닥 큐브 {base}를 찾지 못함")
            return False
        b = self.map[base]
        self.tower, self.height = (b.x, b.y, b.yaw), 1
        # The base may already carry cubes from an earlier attempt.
        for color in self.order[1:]:
            if color not in self.map:  # not on the table: maybe already stacked
                s = yield from self.check_top(color, self.height)
                if s is None:
                    self.say("fail", f"{color} 큐브를 찾지 못함")
                    return False
                self.tower, self.height = (s.x, s.y, s.yaw), self.height + 1
                continue
            for _ in range(PICK_TRIES):
                if (yield from self.pick(color)):
                    break
                yield from self.look()
                if color not in self.map:
                    return False
            else:
                self.say("fail", f"{color} 큐브를 {PICK_TRIES}번 모두 놓침")
                return False
            yield from self.place(color)
            s = yield from self.check_top(color, self.height)
            if s is None:
                return False
            self.tower, self.height = (s.x, s.y, s.yaw), self.height + 1
        return True

    def final_check(self):
        self.say("final", "고정 카메라로 탑 확인")
        yield from self.move(PARK)
        yield from self.wait(0.5)
        # Each cube is cast onto its own layer's plane. The top shows its top
        # face (~1 mm accurate); lower ones show at most a side face, which
        # lands ~14 mm toward the camera, or are hidden. A cube left on the
        # table lands far away (cubes start >= 70 mm apart).
        rgb = self.top.capture(self.d)
        view = rgb.copy()
        x, y = self.tower[:2]
        s, stray = None, []
        for level, color in enumerate(self.order):
            seen = self.top.find(self.d, color, self.plane(level), rgb, view=view)
            if color == self.order[-1]:
                s = seen
            elif seen and math.hypot(seen.x - x, seen.y - y) > SIDE_TOL:
                stray.append(color)
        self.top.last_view = view
        if s and math.hypot(s.x - x, s.y - y) <= ALIGN_TOL * 2 and not stray:
            self.result = "stacked"
            self.say("done", f"성공: {' → '.join(self.order)} 순서로 쌓았습니다")
        else:
            self.result = "failed"
            self.say(
                "fail", f"탑이 완성되지 않았습니다 (따로 놓인 큐브: {stray or '없음'})"
            )
        yield from self.move(START)
