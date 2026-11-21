import math

import mujoco
import numpy as np
from sim import arm
from stack import scene
from stack.eye import FixedEye, WristEye
from stack.stacker import PARK


def test_fixed_camera_maps_all_cubes_accurately(world):
    m, d, sim = world
    sim.reset_to(PARK)
    eye = FixedEye(m)
    s = scene.cube_size(m)
    rng = np.random.default_rng(7)
    for _ in range(10):
        scene.place_layout(m, d, scene.random_layout(rng))
        found = eye.find_all(d, s / 2)
        assert set(found) == set(scene.COLORS)
        for c, f in found.items():
            p, yaw = scene.cube_pose(m, d, c)
            assert math.hypot(f.x - p[0], f.y - p[1]) < 0.004
            assert abs((math.degrees(f.yaw - yaw) + 45) % 90 - 45) < 6
    eye.close()


def test_parked_yellow_arm_is_not_a_yellow_cube(world):
    m, d, sim = world
    sim.reset_to(PARK)
    scene.place_cube(m, d, "yellow", -0.5, 0.5)  # out of view
    mujoco.mj_forward(m, d)
    eye = FixedEye(m)
    assert eye.find(d, "yellow", scene.cube_size(m) / 2) is None
    eye.close()


def test_wrist_jaw_masks_hide_the_yellow_gripper(world, monkeypatch):
    # In the render the jaws are hue 24 and the cube 28, so the default band
    # already separates them. Widen it, as uneven real lighting would force,
    # and the learned jaw mask must still keep the gripper out.
    from stack import colors

    monkeypatch.setitem(
        colors.HSV, "yellow", {**colors.HSV["yellow"], "bands": [(20, 35)]}
    )
    m, d, sim = world
    eye = WristEye(m)
    eye.gripper_q = sim.gripper_q
    sim.reset_to({**PARK, "motor_6": arm.GRIPPER_OPEN_TICK})
    eye.learn_jaws(d, sim.gripper_q())
    # Look down at an empty table: only the jaws are yellow in view.
    for c in scene.COLORS:
        scene.place_cube(m, d, c, -0.5, 0.5)
    from sim.world import START

    sim.reset_to(START)
    raw = eye.capture(d)
    import cv2

    jaws = colors.mask(cv2.cvtColor(raw, cv2.COLOR_RGB2BGR), "yellow") > 0
    assert jaws.sum() > 500, "the jaws should show up yellow in the wrist camera"
    assert eye.color_pixels(d, "yellow").sum() == 0
    eye.close()
