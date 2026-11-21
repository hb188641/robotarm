"""The stacking simulation on its own thread, for the browser panel.

Same contract as `sim.world.World` (the pick panel): the web server sends
commands with `call()`, which run between physics steps, and reads `state()`
and `frame()`, which this thread publishes every frame. Only the scene, the
commands and the published state differ, so this subclasses World.
"""

from __future__ import annotations

import math
import time

import cv2
import mujoco
import numpy as np
from sim.physics_arm import SimArm
from sim.world import (
    FPS,
    START,
    TABLE_LIMIT,
    VIDEO_EVERY,
    VIDEO_SIZE,
    CommandError,
    World,
)

from TITI.voice_motor import kinematics as kin

from . import referee, scene
from .eye import FixedEye, WristEye
from .stacker import HOVER, Stacker

STREAMS = ("overview", "top", "wrist", "top_seen", "wrist_seen")
SETTLE = 2.0  # s the finished tower must stand before it is graded
MIN_BASE_DISTANCE = 0.09  # m: cubes closer to the base sit inside the arm's shadow zone


class StackWorld(World):
    streams = STREAMS

    def __init__(self, profile: dict | None = None, seed: int | None = None):
        super().__init__(profile, seed)
        self.order = tuple(scene.COLORS)
        self.layout: dict = {}
        self.stacks_ok = self.stacks_total = 0
        self.last_grade: dict | None = None

    # ---- commands (simulation thread, via call) ----
    def start_stack(self) -> None:
        self._require_idle()
        self._start_task("stack", self._stack_once())

    def place_cube(self, color: str, x: float, y: float, yaw_deg: float) -> dict:
        if self.task is not None:
            raise CommandError(
                "팔이 움직이는 중에는 큐브를 옮길 수 없습니다. 먼저 정지하세요."
            )
        if color not in scene.COLORS:
            raise CommandError(f"모르는 색입니다: {color}")
        if abs(x) > TABLE_LIMIT or abs(y) > TABLE_LIMIT:
            raise CommandError("책상 밖입니다.")
        if math.hypot(x, y) < MIN_BASE_DISTANCE:
            raise CommandError("로봇 받침대와 너무 가깝습니다.")
        for other in scene.COLORS:
            if other == color:
                continue
            p, _ = scene.cube_pose(self.m, self.d, other)
            if math.hypot(p[0] - x, p[1] - y) < scene.MIN_GAP * 0.75:
                raise CommandError(
                    "다른 큐브와 너무 가깝습니다 (집게가 들어갈 자리가 필요해요)."
                )
        yaw = math.radians(yaw_deg)
        scene.place_cube(self.m, self.d, color, x, y, yaw)
        mujoco.mj_forward(self.m, self.d)
        self.layout = self._current_layout()
        reachable = self._reachable(x, y, yaw)
        self._say(
            f"{color} 큐브를 x={x * 1000:.0f} y={y * 1000:.0f} mm, {yaw_deg:.0f}°에 놓았습니다"
            + ("" if reachable else " (팔이 닿지 않는 위치)")
        )
        return {"reachable": reachable}

    def random_cube(self) -> dict:
        """Scatter all three cubes again (the 🎲 button)."""
        self._require_idle()
        self._shuffle()
        return {}

    def set_order(self, order) -> None:
        order = tuple(order)
        if sorted(order) != sorted(scene.COLORS):
            raise CommandError("빨강·노랑·파랑을 한 번씩 골라 주세요.")
        self._require_idle()
        self.order = self.stacker.order = order
        self._say("쌓는 순서 (아래→위): " + " → ".join(order))

    def reset(self) -> None:
        """Back to the start of this layout: arm at home, cubes where they began."""
        self._cancel()
        self.auto = False
        self._restore(self.layout)
        self.stacker.say("idle", "처음 상태로 되돌렸습니다")

    def stop(self) -> None:
        self._cancel()
        self.auto = False
        self.sim.command(self.sim.ticks(), speed=3.0)
        self.stacker.say("idle", "정지했습니다")

    def set_auto(self, enabled: bool) -> None:
        if enabled and self.task is not None and self.task_name != "auto":
            raise CommandError("지금 작업이 끝난 뒤에 자동 반복을 켜세요.")
        self.auto = bool(enabled)
        if self.auto and self.task is None:
            self._start_task("auto", self._auto_cycle())
        self._say(
            "자동 반복을 켰습니다 (쌓기 → 채점 → 새 배치)"
            if self.auto
            else "자동 반복을 끕니다 (이번 쌓기까지)"
        )

    # ---- tasks ----
    def _stack_once(self):
        yield from self.stacker.run()
        self.stacker.say(self.stacker.stage, self.stacker.status + " · 채점 대기")
        yield from self.stacker.wait(SETTLE)
        self._grade()

    def _grade(self):
        """Referee: the cubes' true poses, compared with the stacker's own verdict."""
        g = referee.grade(self.m, self.d, self.order)
        claim = self.stacker.result
        g["claim"] = claim
        self.last_grade = g
        self.stacks_total += 1
        self.stacks_ok += int(g["stacked"])
        right = g["stacked"] == (claim == "stacked")
        self.verdicts_wrong += 0 if right else 1
        detail = ", ".join(
            f"{L['color']} {L['offset_mm']:.1f}mm" for L in g["layers"][1:]
        )
        self._say(
            "채점 (시뮬레이터 정답): "
            + ("쌓였음" if g["stacked"] else "안 쌓였음")
            + f" ({detail}) → "
            + ("판정 맞음" if right else "판정 틀림!")
        )

    def _auto_cycle(self):
        while self.auto:
            yield from self._stack_once()
            yield from self.stacker.wait(1.0)
            if self.auto:
                self._shuffle()
        self.stacker.say("idle", "자동 반복을 멈췄습니다")

    def _home(self):
        self.stacker.say("home", "처음 자세로 가는 중")
        yield from self.stacker.move(START)
        self.stacker.say("idle", "처음 자세입니다")

    # ---- helpers ----
    def _shuffle(self):
        self.layout = scene.random_layout(self.rng)
        self._restore(self.layout, keep_arm=self.task is not None)
        self._say("큐브를 새로 흩어 놓았습니다")

    def _restore(self, layout, keep_arm=False):
        if not keep_arm:
            mujoco.mj_resetData(self.m, self.d)
            self.sim.reset_to(START)
        scene.place_layout(self.m, self.d, layout)
        self.stacker.map, self.stacker.tower = {}, None
        self.stacker.result = None
        self.wrist.last_view = self.top.last_view = None

    def _current_layout(self) -> dict:
        out = {}
        for c in scene.COLORS:
            p, yaw = scene.cube_pose(self.m, self.d, c)
            out[c] = (float(p[0]), float(p[1]), float(yaw))
        return out

    def _reachable(self, x, y, yaw) -> bool:
        try:
            for up in (0.0, HOVER):
                self.stacker.open_pose(x, y, yaw, 0, up)
        except kin.Unreachable:
            return False
        return True

    # ---- thread ----
    def _run(self):
        try:
            self.m = scene.build_model(self.profile)
            self.d = mujoco.MjData(self.m)
            self.sim = SimArm(self.m, self.d)
            self.wrist = WristEye(self.m)
            self.top = FixedEye(self.m)
            self.stacker = Stacker(
                self.sim,
                self.wrist,
                self.top,
                scene.cube_size(self.m),
                self.order,
                log=self._say,
            )
            self.picker = self.stacker  # World's stop/failure handling talks to .picker
            self.video = mujoco.Renderer(self.m, *VIDEO_SIZE)
            self.layout = scene.random_layout(self.rng)
            self._restore(self.layout)
            self._seen_ids = {}
            self._publish(render=True)
        except Exception as exc:
            self._error = exc
            self._ready.set()
            raise
        self._ready.set()

        frame = 0
        while not self._stop.is_set():
            begin = time.monotonic()
            self._drain_commands()
            self.sim.step(self.speed / FPS)
            self._advance_task()
            frame += 1
            self._publish(render=frame % VIDEO_EVERY == 0)
            time.sleep(max(0.0, 1 / FPS - (time.monotonic() - begin)))
        self.wrist.close()
        self.top.close()
        self.video.close()
        with self._frame_ready:
            self._frame_ready.notify_all()

    def _publish(self, render: bool):
        new = {}
        if render:
            for cam in ("overview", "top", "wrist"):
                self.video.update_scene(self.d, cam)
                new[cam] = self._jpeg(self.video.render())
        for name, eye in (("top_seen", self.top), ("wrist_seen", self.wrist)):
            view = eye.last_view
            if view is None and self._frame_ids[name] == 0:
                view = np.zeros((240, 320, 3), np.uint8)  # "nothing yet" placeholder
                cv2.putText(
                    view, "-", (150, 130), cv2.FONT_HERSHEY_SIMPLEX, 1, (90, 90, 90), 2
                )
            if view is not None and id(view) != self._seen_ids.get(name):
                self._seen_ids[name] = id(view)
                new[name] = self._jpeg(view)
        if new:
            now = time.monotonic()
            with self._frame_ready:
                for name, jpg in new.items():
                    self._frames[name] = jpg
                    self._frame_ids[name] += 1
                    self._frame_times[name] = now
                self._frame_ready.notify_all()

        st = self.stacker
        cubes = {}
        for c in scene.COLORS:
            p, yaw = scene.cube_pose(self.m, self.d, c)
            cubes[c] = {
                "x": float(p[0]),
                "y": float(p[1]),
                "z": float(p[2]),
                "yaw_deg": math.degrees(yaw),
            }
        tip = self.d.site("grasp").xpos
        state = {
            "time": round(self.d.time, 2),
            "stage": st.stage,
            "status": st.status,
            "result": st.result,
            "busy": self.task is not None,
            "task": self.task_name,
            "auto": self.auto,
            "speed": self.speed,
            "order": list(self.order),
            "stacks": {
                "ok": self.stacks_ok,
                "total": self.stacks_total,
                "misjudged": self.verdicts_wrong,
            },
            "grade": self.last_grade,
            "cubes": cubes,
            "cube_size": scene.cube_size(self.m),
            "seen": {
                c: {"x": s.x, "y": s.y, "yaw_deg": math.degrees(s.yaw)}
                for c, s in st.map.items()
            },
            "tower": None
            if st.tower is None
            else {"x": st.tower[0], "y": st.tower[1], "height": st.height},
            "tip": {"x": float(tip[0]), "y": float(tip[1]), "z": float(tip[2])},
            "ticks": self.sim.ticks(),
            "log": list(self.log)[-14:],
        }
        with self._lock:
            self._state = state


__all__ = ["STREAMS", "CommandError", "StackWorld"]
