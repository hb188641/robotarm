"""The pick simulation running on its own thread, driven by commands.

MuJoCo data and the OpenGL renderers belong to one thread, so the web server
never touches them: it sends commands with `call()` (run between physics
steps, result returned to the caller) and reads `state()` / `frame()`, which
the simulation thread publishes every frame.
"""

from __future__ import annotations

import math
import queue
import re
import threading
import time
import traceback
from collections import deque
from concurrent.futures import Future

import cv2
import mujoco
import numpy as np

from TITI.voice_motor import kinematics as kin

from . import arm, scene
from .eye import WristEye
from .physics_arm import SimArm
from .picker import HOVER, LIFT, Picker

FPS = 60
VIDEO_EVERY = 3  # render the video streams every 3rd physics frame (20 fps)
VIDEO_SIZE = (480, 640)  # height, width
TABLE_LIMIT = 0.34  # the cube must stay on the visible table (|x|, |y| in m)
# The taught "대기" (standby) pose from voice_motor/poses.json, gripper open.
START = {
    "motor_1": 2048,
    "motor_2": 1606,
    "motor_3": 2135,
    "motor_4": 2781,
    "motor_5": 2048,
    "motor_6": arm.GRIPPER_OPEN_TICK,
}
STREAMS = ("wrist", "overview", "detector")


class CommandError(Exception):
    """A command that cannot run now; the message is shown to the user."""


class World:
    def __init__(self, profile: dict | None = None, seed: int | None = None):
        self.profile = profile
        self.rng = np.random.default_rng(seed)
        self._commands: queue.Queue = queue.Queue()
        self._lock = threading.Lock()
        self._frame_ready = threading.Condition()
        self._frames: dict[str, bytes] = {}
        self._frame_ids = dict.fromkeys(STREAMS, 0)
        self._frame_times = dict.fromkeys(STREAMS, 0.0)  # time.monotonic() of render
        self._state: dict = {}
        self._ready = threading.Event()
        self._stop = threading.Event()
        self._error: BaseException | None = None
        self.log: deque = deque(maxlen=60)
        self.speed = 1.0
        self.auto = False
        self.task = None
        self.task_name = ""
        self.holding = False
        self.picks_ok = self.picks_total = 0
        self.verdicts_wrong = 0  # referee: picker verdicts the true height contradicts
        self.cube_spot = (0.22, 0.05, math.radians(20))
        self.thread = threading.Thread(target=self._run, name="sim", daemon=True)

    # ---- lifecycle (any thread) ----
    def start(self, timeout=30.0) -> World:
        self.thread.start()
        if not self._ready.wait(timeout):
            raise RuntimeError("시뮬레이터가 시작되지 않았습니다.")
        if self._error:
            raise RuntimeError(f"시뮬레이터 시작 실패: {self._error}")
        return self

    def close(self) -> None:
        self._stop.set()
        self.thread.join(timeout=5)

    def call(self, fn, *args, timeout=10.0):
        """Run `fn(*args)` on the simulation thread and return its result."""
        future: Future = Future()
        self._commands.put((fn, args, future))
        return future.result(timeout=timeout)

    def state(self) -> dict:
        with self._lock:
            return dict(self._state)

    def frame(
        self, name: str, after: int = 0, timeout: float = 2.0
    ) -> tuple[int, bytes]:
        """Latest JPEG of a stream, waiting for one newer than `after`."""
        fid, _, jpg = self.frame_at(name, after, timeout)
        return fid, jpg

    def frame_at(
        self, name: str, after: int = 0, timeout: float = 2.0
    ) -> tuple[int, float, bytes]:
        """Like frame(), plus when it was rendered (time.monotonic())."""
        with self._frame_ready:
            self._frame_ready.wait_for(
                lambda: self._frame_ids[name] > after or self._stop.is_set(), timeout
            )
            return (
                self._frame_ids[name],
                self._frame_times[name],
                self._frames.get(name, b""),
            )

    # ---- commands (run on the simulation thread via call) ----
    def place_cube(self, x: float, y: float, yaw_deg: float) -> dict:
        """From the browser: only while the arm is idle."""
        if self.task is not None:
            raise CommandError(
                "팔이 움직이는 중에는 큐브를 옮길 수 없습니다. 먼저 정지하세요."
            )
        return self._put_cube(x, y, yaw_deg)

    def random_cube(self) -> dict:
        if self.task is not None:
            raise CommandError(
                "팔이 움직이는 중에는 큐브를 옮길 수 없습니다. 먼저 정지하세요."
            )
        return self._random_cube()

    def _random_cube(self) -> dict:
        x, y, yaw = scene.random_cube_spot(self.rng)
        return self._put_cube(x, y, math.degrees(yaw))

    def _put_cube(self, x: float, y: float, yaw_deg: float) -> dict:
        """Teleport the cube (also used by the auto cycle, mid-task)."""
        if abs(x) > TABLE_LIMIT or abs(y) > TABLE_LIMIT:
            raise CommandError("책상 밖입니다.")
        if math.hypot(x, y) < 0.07:
            raise CommandError("로봇 받침대와 겹치는 위치입니다.")
        self.cube_spot = (x, y, math.radians(yaw_deg))
        scene.place_cube(self.m, self.d, *self.cube_spot)
        self.holding = False
        mujoco.mj_forward(self.m, self.d)
        reachable = self._reachable(x, y, math.radians(yaw_deg))
        self._say(
            f"큐브를 x={x * 1000:.0f} y={y * 1000:.0f} mm, {yaw_deg:.0f}°에 놓았습니다"
            + ("" if reachable else " (팔이 닿지 않는 위치)")
        )
        return {"reachable": reachable}

    def pick(self) -> None:
        self._require_idle()
        self._start_task("pick", self._pick_once())

    def put_back(self) -> None:
        self._require_idle()
        if not self.holding:
            raise CommandError("들고 있는 큐브가 없습니다.")
        self._start_task("place", self._put_back())

    def home(self) -> None:
        self._require_idle()
        self._start_task("home", self._home())

    def stop(self) -> None:
        self._cancel()
        self.auto = False
        self.sim.command(self.sim.ticks(), speed=3.0)  # hold where it is now
        self.picker.say("idle", "정지했습니다")

    def reset(self) -> None:
        self._cancel()
        self.auto = False
        mujoco.mj_resetData(self.m, self.d)
        self.sim.reset_to(START)
        scene.place_cube(self.m, self.d, *self.cube_spot)
        mujoco.mj_forward(self.m, self.d)
        self.holding = False
        self.picker.sighting = None
        self.picker.result = None
        self.eye.last_view = None
        self.picker.say("idle", "처음 상태로 되돌렸습니다")

    def set_auto(self, enabled: bool) -> None:
        if enabled and self.task is not None and self.task_name != "auto":
            raise CommandError("지금 작업이 끝난 뒤에 자동 반복을 켜세요.")
        self.auto = bool(enabled)
        if self.auto and self.task is None:
            self._start_task("auto", self._auto_cycle())
        self._say(
            "자동 반복을 켰습니다"
            if self.auto
            else "자동 반복을 끕니다 (이번 동작까지)"
        )

    def set_speed(self, value: float) -> None:
        self.speed = float(min(max(value, 0.25), 4.0))

    # ---- tasks (generators advanced once per frame) ----
    def _pick_once(self):
        yield from self.picker.run()
        self.picks_total += 1
        if self.picker.result == "lifted":
            self.picks_ok += 1
            self.holding = True
        if self.picker.result in ("lifted", "dropped"):
            self._grade()

    def _grade(self):
        """Referee: compare the picker's verdict (camera + gripper only) with
        the truth only the simulator knows, the cube's real height."""
        height = scene.cube_pose(self.m, self.d)[0][2] - scene.cube_size(self.m) / 2
        really = height > LIFT * 0.6
        right = really == (self.picker.result == "lifted")
        self.verdicts_wrong += 0 if right else 1
        self._say(
            f"채점 (시뮬레이터 정답): 큐브 높이 {height * 1000:.0f} mm → "
            + ("판정 맞음" if right else "판정 틀림!")
        )

    def _put_back(self):
        yield from self.picker.put_back()
        self.holding = False
        s = self.picker.sighting
        if s is not None:
            self.cube_spot = (*scene.cube_pose(self.m, self.d)[0][:2], s.yaw)
        self.picker.say("idle", "내려놓았습니다")

    def _home(self):
        self.picker.say("home", "처음 자세로 가는 중")
        yield from self.picker.move(START)
        self.holding = False
        self.picker.say("idle", "처음 자세입니다")

    def _auto_cycle(self):
        while self.auto:
            yield from self._pick_once()
            yield from self.picker.wait(1.2)
            if self.holding:
                yield from self.picker.put_back()
                self.holding = False
            yield from self.picker.wait(0.4)
            if self.auto:
                self._random_cube()  # its own task is running: skip the idle check
        self.picker.say("idle", "자동 반복을 멈췄습니다")

    # ---- internals (simulation thread) ----
    def _require_idle(self):
        if self.task is not None:
            raise CommandError("다른 동작이 진행 중입니다.")

    def _start_task(self, name, generator):
        self.task, self.task_name = generator, name

    def _cancel(self):
        if self.task is not None:
            self.task.close()
        self.task, self.task_name = None, ""

    def _say(self, message: str):
        message = re.sub(r"^\[\w+\] ", "", message)  # Picker's "[stage] " tag
        self.log.append({"t": round(self.d.time, 1), "msg": message})

    def _reachable(self, x, y, yaw) -> bool:
        try:
            for up in (0.0, HOVER, LIFT):
                self.picker.grasp_pose(x, y, yaw, up)
        except kin.Unreachable:
            return False
        return True

    def _advance_task(self):
        if self.task is None:
            return
        try:
            next(self.task)
        except StopIteration:
            self.task, self.task_name = None, ""
        except kin.Unreachable as exc:
            self.task, self.task_name = None, ""
            self.auto = False
            self.picker.result = "unreachable"
            self.picker.say("fail", f"실패: {exc}")
        except Exception as exc:  # noqa: BLE001 - a broken task must not kill the simulation
            traceback.print_exc()
            self.task, self.task_name = None, ""
            self.auto = False
            self.picker.result = "error"
            self.picker.say("fail", f"오류로 동작을 멈췄습니다: {exc}")

    def _run(self):
        try:
            self.m = scene.build_pick_model(self.profile)
            self.d = mujoco.MjData(self.m)
            self.sim = SimArm(self.m, self.d)
            self.eye = WristEye(self.m)
            self.picker = Picker(self.sim, self.eye, log=self._say)
            self.video = mujoco.Renderer(self.m, *VIDEO_SIZE)
            self.sim.reset_to(START)
            scene.place_cube(self.m, self.d, *self.cube_spot)
            mujoco.mj_forward(self.m, self.d)
            self._last_view_id = None
            self._publish(render=True)
        except Exception as exc:  # report startup failures to start()
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
        self.eye.close()
        self.video.close()
        with self._frame_ready:
            self._frame_ready.notify_all()

    def _drain_commands(self):
        while True:
            try:
                fn, args, future = self._commands.get_nowait()
            except queue.Empty:
                return
            try:
                result = fn(*args)
            except Exception as exc:  # noqa: BLE001 - re-raised in the caller via the future
                future.set_exception(exc)
                continue
            self._publish(render=False)  # the reply carries the state after the command
            future.set_result(result)

    def _jpeg(self, rgb: np.ndarray) -> bytes:
        ok, buf = cv2.imencode(".jpg", rgb[:, :, ::-1], [cv2.IMWRITE_JPEG_QUALITY, 80])
        return buf.tobytes() if ok else b""

    def _publish(self, render: bool):
        new = {}
        if render:
            for cam in ("wrist", "overview"):
                self.video.update_scene(self.d, cam)
                new[cam] = self._jpeg(self.video.render())
        view = self.eye.last_view
        if view is not None and id(view) != self._last_view_id:
            self._last_view_id = id(view)
            new["detector"] = self._jpeg(view)
        if new:
            now = time.monotonic()
            with self._frame_ready:
                for name, jpg in new.items():
                    self._frames[name] = jpg
                    self._frame_ids[name] += 1
                    self._frame_times[name] = now
                self._frame_ready.notify_all()

        cube, yaw = scene.cube_pose(self.m, self.d)
        tip = self.d.site("grasp").xpos
        s = self.picker.sighting
        state = {
            "time": round(self.d.time, 2),
            "stage": self.picker.stage,
            "status": self.picker.status,
            "result": self.picker.result,
            "busy": self.task is not None,
            "task": self.task_name,
            "auto": self.auto,
            "speed": self.speed,
            "holding": self.holding,
            "picks": {
                "ok": self.picks_ok,
                "total": self.picks_total,
                "misjudged": self.verdicts_wrong,
            },
            "cube": {
                "x": float(cube[0]),
                "y": float(cube[1]),
                "z": float(cube[2]),
                "yaw_deg": math.degrees(yaw),
            },
            "cube_size": scene.cube_size(self.m),
            "tip": {"x": float(tip[0]), "y": float(tip[1]), "z": float(tip[2])},
            "sighting": None
            if s is None
            else {"x": s.x, "y": s.y, "yaw_deg": math.degrees(s.yaw)},
            "ticks": self.sim.ticks(),
            "log": list(self.log)[-14:],
        }
        with self._lock:
            self._state = state
