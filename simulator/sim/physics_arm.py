"""The simulated arm driven like the real one: raw-tick goals, servo-like motion.

Each `command(ticks)` starts a smooth joint-space move from the current goal to
the new one at a limited speed (the STS3215 does not jump); the model's position
actuators (kp ≈ 1000, ±3.35 N·m like the real servo stall torque) track it.
"""

from __future__ import annotations

import mujoco
import numpy as np

from . import arm

DEFAULT_SPEED = 1.2  # rad/s for the joint that moves farthest


class SimArm:
    def __init__(self, model: mujoco.MjModel, data: mujoco.MjData, speed=DEFAULT_SPEED):
        self.m, self.d = model, data
        self.speed = speed
        self._act = [model.actuator(arm.JOINTS[m]).id for m in arm.MOTORS]
        self._qadr = [
            model.jnt_qposadr[model.joint(arm.JOINTS[m]).id] for m in arm.MOTORS
        ]
        self._vadr = [
            model.jnt_dofadr[model.joint(arm.JOINTS[m]).id] for m in arm.MOTORS
        ]
        self._start = self.goal = self.d.ctrl[self._act].copy()
        self._t0 = self._t1 = 0.0

    # ---- pose ----
    def reset_to(self, ticks: dict) -> None:
        """Teleport (no motion) to `ticks`, at rest, and hold there."""
        arm.set_ticks(self.m, self.d, ticks)
        self.d.qvel[self._vadr] = 0
        self._start = self.goal = self.d.ctrl[self._act].copy()
        self._t0 = self._t1 = self.d.time
        mujoco.mj_forward(self.m, self.d)

    def ticks(self) -> dict[str, int]:
        """Measured positions, like GET /api/state."""
        return arm.get_ticks(self.m, self.d)

    def goal_ticks(self) -> dict[str, int]:
        return {m: arm.q_to_tick(m, q) for m, q in zip(arm.MOTORS, self.goal)}

    # ---- motion ----
    def command(self, ticks: dict, speed: float | None = None) -> float:
        """Start moving the given motors toward `ticks`; returns the move time (s)."""
        now = self.d.time
        current = self._setpoint(now)
        goal = current.copy()
        for i, motor in enumerate(arm.MOTORS):
            if motor in ticks:
                goal[i] = arm.tick_to_q(motor, ticks[motor])
        lo = self.m.actuator_ctrlrange[self._act, 0]
        hi = self.m.actuator_ctrlrange[self._act, 1]
        goal = np.clip(goal, lo, hi)
        travel = float(np.abs(goal - current).max())
        duration = max(travel / (speed or self.speed), 0.05)
        self._start, self.goal = current, goal
        self._t0, self._t1 = now, now + duration
        return duration

    def _setpoint(self, t: float) -> np.ndarray:
        if t >= self._t1:
            return self.goal.copy()
        s = (t - self._t0) / (self._t1 - self._t0)
        s = s * s * (3 - 2 * s)  # smoothstep: no velocity jump at either end
        return self._start + (self.goal - self._start) * s

    @property
    def moving(self) -> bool:
        return self.d.time < self._t1

    def settled(self, tol_rad=0.02, tol_vel=0.05) -> bool:
        """Done moving and every arm joint (not the gripper) near its goal and still."""
        if self.moving:
            return False
        err = np.abs(self.d.qpos[self._qadr[:5]] - self.goal[:5]).max()
        vel = np.abs(self.d.qvel[self._vadr[:5]]).max()
        return err < tol_rad and vel < tol_vel

    def gripper_q(self) -> float:
        return float(self.d.qpos[self._qadr[5]])

    def step(self, seconds: float) -> None:
        """Advance physics by `seconds`, updating the servo setpoint every step."""
        n = max(1, round(seconds / self.m.opt.timestep))
        for _ in range(n):
            self.d.ctrl[self._act] = self._setpoint(self.d.time)
            mujoco.mj_step(self.m, self.d)
