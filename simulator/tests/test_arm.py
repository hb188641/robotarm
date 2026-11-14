"""The MuJoCo model must agree with the project's own conventions and kinematics."""

import json

import mujoco
import numpy as np
import pytest
from sim import arm

from TITI.voice_motor import kinematics as kin

PROFILE = arm.load_profile()


@pytest.fixture(scope="module")
def model():
    return arm.build_model(PROFILE)


def limits(motor):
    joint = (PROFILE or {}).get("joints", {}).get(motor) or {}
    return joint.get("min") or 900, joint.get("max") or 3200


def test_grasp_site_matches_voice_motor_kinematics(model):
    data = mujoco.MjData(model)
    rng = np.random.default_rng(1)
    for _ in range(300):
        ticks = {m: int(rng.integers(*limits(m))) for m in arm.ARM}
        arm.set_ticks(model, data, ticks)
        mujoco.mj_kinematics(model, data)
        np.testing.assert_allclose(
            arm.grasp_pose(model, data), kin.fk(ticks), atol=1e-4
        )


def test_taught_grasps_sit_on_the_table(model):
    """pick.json grasps were taught by hand on a cube on the table, so every tip
    sits just above the model's floor (z = 0): the base frame is on the table."""
    points = json.loads((arm.REPO / "TITI/voice_motor/pick.json").read_text())["points"]
    data = mujoco.MjData(model)
    heights = []
    for point in points:
        arm.set_ticks(model, data, point["joints"])
        mujoco.mj_kinematics(model, data)
        heights.append(data.site("grasp").xpos[2])
    assert 0.0 < min(heights) and max(heights) < 0.035


@pytest.mark.parametrize("motor", arm.MOTORS)
def test_ticks_round_trip(model, motor):
    data = mujoco.MjData(model)
    lo, hi = limits(motor)
    for tick in (lo, (lo + hi) // 2, hi):
        arm.set_ticks(model, data, {motor: tick})
        assert arm.get_ticks(model, data)[motor] == tick


def test_center_tick_is_urdf_zero():
    assert arm.tick_to_q("motor_3", 2048) == 0
    assert arm.tick_to_q("motor_1", 2048 + 1024) == pytest.approx(np.pi / 2)


def test_gripper_open_tick_opens_the_jaw(model):
    closed = arm.tick_to_q("motor_6", arm.GRIPPER_CLOSED_TICK)
    opened = arm.tick_to_q("motor_6", arm.GRIPPER_OPEN_TICK)
    low, high = model.joint("gripper").range
    assert low <= closed < opened <= high


def test_model_ranges_cover_measured_limits(model):
    for motor in arm.MOTORS:
        lo, hi = limits(motor)
        q = sorted((arm.tick_to_q(motor, lo), arm.tick_to_q(motor, hi)))
        jlo, jhi = model.joint(arm.JOINTS[motor]).range
        assert jlo <= q[0] + 1e-9 and q[1] <= jhi + 1e-9, motor
