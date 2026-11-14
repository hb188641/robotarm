"""Pick scene: the SO-101 on its table, a wrist camera and a free red cube.

The wrist camera is the robot's first-person view. It sits on the gripper, behind
and beside the fingers, looking past the fingertips, roughly where the SO-101
wrist camera mount puts a 32x32 UVC module.

    build_pick_model(profile, cube_size) → MjModel with camera "wrist" and
                                            free body "cube"
    place_cube(model, data, x, y, yaw)   → put the cube on the table
"""

from __future__ import annotations

import math

import mujoco
import numpy as np

from . import arm

CUBE_SIZE = 0.025  # edge length (m)
CUBE_MASS = 0.02
WRIST_FOVY = 70.0

# Camera pose in the grasp frame (z = out of the gripper, x = jaw closing dir).
# 75 mm back from the grasp point and 38 mm to the side, aimed 70 mm past it.
CAM_POS = np.array([0.0, 0.038, -0.075])
CAM_AIM = np.array([0.0, 0.0, 0.07])


def _rot_to_quat(r: np.ndarray) -> list[float]:
    q = np.zeros(4)
    mujoco.mju_mat2Quat(q, r.flatten())
    return q.tolist()


def _grasp_frame() -> tuple[np.ndarray, np.ndarray]:
    """Grasp site pose in the gripper body frame (position, rotation)."""
    rot = np.zeros(9)
    mujoco.mju_quat2Mat(rot, np.array(arm.GRASP_QUAT))
    return np.array(arm.GRASP_POS), rot.reshape(3, 3)


def wrist_camera_pose() -> tuple[np.ndarray, np.ndarray]:
    """Camera position and rotation in the gripper body frame.

    MuJoCo cameras look along their -z with +y up in the image. "Up" is chosen
    away from the fingers, so the jaws show at the bottom of the picture.
    """
    forward = CAM_AIM - CAM_POS
    forward /= np.linalg.norm(forward)
    z = -forward
    up = np.array([0.0, 1.0, 0.0])
    y = up - (up @ z) * z
    y /= np.linalg.norm(y)
    x = np.cross(y, z)
    cam_in_grasp = np.column_stack([x, y, z])
    g_pos, g_rot = _grasp_frame()
    return g_pos + g_rot @ CAM_POS, g_rot @ cam_in_grasp


# Fingertip pads, in the grasp frame with the gripper joint at 0 (mm → m).
# Measured from the meshes: at q = 0 both fingertip inner faces are 7.9 mm off
# the grasp axis (fixed jaw +x, moving jaw -x), about 12 mm wide, and reach
# 8 mm past the grasp point. Pads cover the last 24 mm of each finger.
PAD_DEPTH = 0.004
PAD_HALF_Y = 0.006
PAD_Z = (-0.015, 0.008)
PAD_FACE_X = 0.0079
CONTACT = {
    "friction": [1.5, 0.02, 0.002],
    "condim": 4,
    "solref": [0.004, 1.0],
    "solimp": [0.95, 0.99, 0.001, 0.5, 2.0],
}


def _pad_center(sign: float) -> np.ndarray:
    return np.array([sign * (PAD_FACE_X + PAD_DEPTH / 2), 0.0, sum(PAD_Z) / 2])


def add_finger_pads(spec: mujoco.MjSpec) -> None:
    """Replace the jaw meshes' collision with box pads on the fingertips.

    MuJoCo collides meshes as convex hulls; the hull of each jaw part fills the
    space between the fingers, so a cube is "touched" before the jaws close and
    gets pushed through. The meshes stay visible; only collision changes.
    """
    jaw = spec.body("moving_jaw_so101_v1")
    for body in (spec.body("gripper"), jaw):
        for geom in body.geoms:
            if geom.type == mujoco.mjtGeom.mjGEOM_MESH and geom.meshname in (
                "wrist_roll_follower_so101_v1",
                "moving_jaw_so101_v1",
            ):
                geom.contype = geom.conaffinity = 0

    g_pos, g_rot = _grasp_frame()
    half = [PAD_DEPTH / 2, PAD_HALF_Y, (PAD_Z[1] - PAD_Z[0]) / 2]
    look = {"rgba": [0.2, 0.6, 1.0, 0.5], "group": 3}

    # Fixed jaw: part of the gripper body.
    spec.body("gripper").add_geom(
        name="fixed_pad",
        type=mujoco.mjtGeom.mjGEOM_BOX,
        size=half,
        pos=(g_pos + g_rot @ _pad_center(+1)).tolist(),
        quat=_rot_to_quat(g_rot),
        **CONTACT,
        **look,
    )
    # Moving jaw: express the q = 0 pad pose in the jaw's own body frame.
    j_rot = np.zeros(9)
    mujoco.mju_quat2Mat(j_rot, np.array(jaw.quat))
    j_rot = j_rot.reshape(3, 3)
    j_pos = np.array(jaw.pos)
    in_gripper = g_pos + g_rot @ _pad_center(-1)
    jaw.add_geom(
        name="moving_pad",
        type=mujoco.mjtGeom.mjGEOM_BOX,
        size=half,
        pos=(j_rot.T @ (in_gripper - j_pos)).tolist(),
        quat=_rot_to_quat(j_rot.T @ g_rot),
        **CONTACT,
        **look,
    )


def build_pick_spec(
    profile: dict | None = None, cube_size: float = CUBE_SIZE
) -> mujoco.MjSpec:
    spec = arm.build_spec(profile)
    spec.option.cone = mujoco.mjtCone.mjCONE_ELLIPTIC
    spec.option.impratio = 10  # stiffer friction: a squeezed cube does not creep
    spec.option.timestep = 0.002

    pos, rot = wrist_camera_pose()
    grip = spec.body("gripper")
    grip.add_camera(
        name="wrist", pos=pos.tolist(), quat=_rot_to_quat(rot), fovy=WRIST_FOVY
    )
    # A small dark box standing in for the camera module (visual only).
    grip.add_geom(
        name="wrist_cam_body",
        type=mujoco.mjtGeom.mjGEOM_BOX,
        pos=(pos + rot @ np.array([0, 0, 0.012])).tolist(),
        quat=_rot_to_quat(rot),
        size=[0.016, 0.016, 0.01],
        rgba=[0.12, 0.12, 0.12, 1],
        contype=0,
        conaffinity=0,
        group=2,
    )

    add_finger_pads(spec)

    half = cube_size / 2
    cube = spec.worldbody.add_body(name="cube", pos=[0.2, 0.0, half])
    cube.add_freejoint(name="cube")
    cube.add_geom(
        name="cube",
        type=mujoco.mjtGeom.mjGEOM_BOX,
        size=[half] * 3,
        mass=CUBE_MASS,
        rgba=[0.85, 0.05, 0.05, 1],
        **CONTACT,
    )

    # A free camera position for the "third person" inset and screenshots.
    spec.worldbody.add_camera(
        name="overview",
        pos=[0.55, -0.45, 0.42],
        xyaxes=[0.63, 0.77, 0, -0.38, 0.31, 0.87],
        fovy=45,
    )
    return spec


def build_pick_model(
    profile: dict | None = None, cube_size: float = CUBE_SIZE
) -> mujoco.MjModel:
    return build_pick_spec(profile, cube_size).compile()


def cube_size(model: mujoco.MjModel) -> float:
    return float(model.geom("cube").size[0] * 2)


def place_cube(model, data, x: float, y: float, yaw: float = 0.0) -> None:
    adr = model.jnt_qposadr[model.joint("cube").id]
    vadr = model.jnt_dofadr[model.joint("cube").id]
    data.qpos[adr : adr + 3] = [x, y, cube_size(model) / 2 + 1e-4]
    data.qpos[adr + 3 : adr + 7] = [math.cos(yaw / 2), 0, 0, math.sin(yaw / 2)]
    data.qvel[vadr : vadr + 6] = 0


def cube_pose(model, data) -> tuple[np.ndarray, float]:
    """Cube center (m) and yaw (radians) from the simulation's ground truth."""
    body = model.body("cube").id
    rot = data.xmat[body].reshape(3, 3)
    return data.xpos[body].copy(), math.atan2(rot[1, 0], rot[0, 0])


def random_cube_spot(rng: np.random.Generator) -> tuple[float, float, float]:
    """A spot on the table in front of the arm, comfortably inside its reach."""
    r = rng.uniform(0.16, 0.26)
    a = rng.uniform(-math.radians(55), math.radians(55))
    return r * math.cos(a), r * math.sin(a), rng.uniform(-math.pi / 4, math.pi / 4)
