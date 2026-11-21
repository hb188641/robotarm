"""First-person pick in simulation: see the cube, grab it, lift it (headless)."""

import math

import mujoco
import numpy as np
import pick_sim
import pytest
from sim import arm, scene
from sim.eye import WristEye
from sim.physics_arm import SimArm
from sim.picker import Picker

START = pick_sim.START


@pytest.fixture(scope="module")
def model():
    return scene.build_pick_model(arm.load_profile())


@pytest.fixture
def setup(model):
    data = mujoco.MjData(model)
    sim = SimArm(model, data)
    eye = WristEye(model)
    sim.reset_to(START)
    yield model, data, sim, eye
    eye.close()


def run(picker, sim, on_stage=None, limit_s=30.0):
    for _ in picker.run():
        sim.step(1 / 60)
        if on_stage:
            on_stage(picker.stage)
        assert sim.d.time < limit_s, "pick did not finish"
    return picker.result


@pytest.mark.parametrize(
    "x, y, yaw_deg",
    [(0.20, 0.0, 0.0), (0.24, -0.10, 30.0), (0.14, 0.12, -40.0), (0.17, -0.18, 10.0)],
)
def test_sees_grabs_and_lifts_the_cube(setup, x, y, yaw_deg):
    model, data, sim, eye = setup
    scene.place_cube(model, data, x, y, math.radians(yaw_deg))
    picker = Picker(sim, eye, log=lambda _: None)
    assert run(picker, sim) == "lifted"
    center, _ = scene.cube_pose(model, data)
    assert center[2] > 0.06
    # The cube rides between the pads, not on top of a closed gripper.
    assert sim.gripper_q() > arm.tick_to_q("motor_6", arm.GRIPPER_CLOSED_TICK) + 0.1


def test_wrist_camera_locates_the_cube_within_a_few_mm(setup):
    model, data, sim, eye = setup
    picker = Picker(sim, eye, log=lambda _: None)
    rng = np.random.default_rng(7)
    for _ in range(6):
        x, y, yaw = scene.random_cube_spot(rng)
        scene.place_cube(model, data, x, y, yaw)
        pan = math.atan2(y, x)
        look = picker.pose_for((0.2 * math.cos(pan), 0.2 * math.sin(pan), 0.09), pan)
        sim.reset_to({**look, "motor_6": arm.GRIPPER_OPEN_TICK})
        seen = eye.find_cube(data, scene.cube_size(model))
        assert seen is not None
        assert math.hypot(seen.x - x, seen.y - y) < 0.008
        assert eye.last_view is not None and eye.last_view.shape == (360, 480, 3)


def test_reports_a_miss_when_the_cube_is_gone(setup):
    model, data, sim, eye = setup
    scene.place_cube(model, data, 0.2, 0.05, 0.0)
    picker = Picker(sim, eye, log=lambda _: None)

    def snatch(stage):
        if stage == "descend":
            scene.place_cube(model, data, 0.45, 0.4, 0.0)  # someone took it

    assert run(picker, sim, snatch) == "missed"


def test_reports_no_cube_when_none_is_in_view(setup):
    model, data, sim, eye = setup
    scene.place_cube(model, data, -0.25, 0.0, 0.0)  # behind the robot
    picker = Picker(sim, eye, log=lambda _: None)
    assert run(picker, sim) == "not_found"


def test_finger_pads_close_on_the_grasp_axis(model):
    """Pads, not the mesh hulls, collide; closed, they nearly meet on the axis."""
    data = mujoco.MjData(model)
    arm.set_ticks(model, data, {**START, "motor_6": arm.GRIPPER_CLOSED_TICK})
    mujoco.mj_forward(model, data)
    fixed, moving = model.geom("fixed_pad").id, model.geom("moving_pad").id
    gap = mujoco.mj_geomDistance(model, data, fixed, moving, 0.05, None)
    assert gap < 0.004
    arm.set_ticks(model, data, {"motor_6": arm.GRIPPER_OPEN_TICK})
    mujoco.mj_forward(model, data)
    assert mujoco.mj_geomDistance(model, data, fixed, moving, 0.2, None) > 0.035
    for name in ("wrist_roll_follower_so101_v1", "moving_jaw_so101_v1"):
        for g in range(model.ngeom):
            if model.geom_dataid[g] == model.mesh(name).id and model.geom_type[g] == 7:
                assert model.geom_contype[g] == 0 and model.geom_conaffinity[g] == 0


def test_headless_cli_lifts_a_given_cube(tmp_path, capsys):
    sheet = tmp_path / "sheet.png"
    pick_sim.main(["--headless", "--cube", "0.22", "0.06", "15", "--sheet", str(sheet)])
    assert "result: lifted" in capsys.readouterr().out
    assert sheet.stat().st_size > 50_000


def test_picker_never_reads_the_true_cube_position(setup, monkeypatch):
    """Like the real arm, the picker may only use the camera, joints and gripper."""
    model, data, sim, eye = setup
    scene.place_cube(model, data, 0.21, 0.04, math.radians(15))

    def forbidden(*_):
        raise AssertionError("picker read the cube's true pose")

    monkeypatch.setattr("sim.picker.scene.cube_pose", forbidden)
    picker = Picker(sim, eye, log=lambda _: None)
    assert run(picker, sim) == "lifted"
    assert "쥐고 있습니다" in picker.status and "일치" in picker.status


def test_a_cube_left_behind_is_reported_as_dropped(setup):
    """The cube slips out as the lift starts: gripper and camera both notice."""
    model, data, sim, eye = setup
    spot = (0.20, -0.03, math.radians(10))
    scene.place_cube(model, data, *spot)
    picker = Picker(sim, eye, log=lambda _: None)
    taken = []

    def slip(stage):
        if stage == "lift" and not taken:
            taken.append(True)
            # knocked out of the jaws onto the table nearby: the jaws are empty
            scene.place_cube(model, data, spot[0], spot[1] + 0.06, spot[2])

    assert run(picker, sim, on_stage=slip) == "dropped"
    assert "따라오지 않았습니다" in picker.status
