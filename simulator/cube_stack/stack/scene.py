"""The stacking scene: SO-101, wrist camera, a fixed camera above the table and
three free cubes (red, yellow, blue).

Built on `sim.scene.build_pick_spec` (wrist camera, finger pads, contact
settings); its single red cube is replaced by three named `cube_<color>`.
"""

from __future__ import annotations

import math

import mujoco
import numpy as np
from sim import scene as base

CUBE_SIZE = base.CUBE_SIZE  # 25 mm
CUBE_MASS = base.CUBE_MASS
COLORS = ("red", "yellow", "blue")
RGBA = {
    "red": [0.85, 0.05, 0.05, 1],
    "yellow": [0.95, 0.85, 0.05, 1],
    "blue": [0.05, 0.20, 0.85, 1],
}
# The fixed camera hangs in the air in front of the arm, looking back and down
# at the work area, so the parked arm stays behind the cubes in its picture.
TOP_CAMERA = "top"
TOP_POS = np.array([0.44, 0.0, 0.56])
TOP_AIM = np.array([0.17, 0.0, 0.0])
TOP_FOVY = 44.0
MIN_GAP = 0.07  # cube centers at least this far apart (open jaws need room)


def _look_at(pos, aim, up=(0, 0, 1)) -> list[float]:
    """MuJoCo camera quaternion looking from `pos` at `aim`."""
    z = np.asarray(pos, float) - np.asarray(aim, float)
    z /= np.linalg.norm(z)
    x = np.cross(up, z)
    if np.linalg.norm(x) < 1e-6:
        x = np.array([0.0, -1.0, 0.0])
    x /= np.linalg.norm(x)
    y = np.cross(z, x)
    q = np.zeros(4)
    mujoco.mju_mat2Quat(q, np.column_stack([x, y, z]).flatten())
    return q.tolist()


def build_spec(profile: dict | None = None, size: float = CUBE_SIZE) -> mujoco.MjSpec:
    spec = base.build_pick_spec(profile, size)
    spec.delete(spec.body("cube"))
    half = size / 2
    for i, color in enumerate(COLORS):
        body = spec.worldbody.add_body(
            name=f"cube_{color}", pos=[0.2, 0.08 * (i - 1), half]
        )
        body.add_freejoint(name=f"cube_{color}")
        body.add_geom(
            name=f"cube_{color}",
            type=mujoco.mjtGeom.mjGEOM_BOX,
            size=[half] * 3,
            mass=CUBE_MASS,
            rgba=RGBA[color],
            **base.CONTACT,
        )
    spec.worldbody.add_camera(
        name=TOP_CAMERA,
        pos=TOP_POS.tolist(),
        quat=_look_at(TOP_POS, TOP_AIM),
        fovy=TOP_FOVY,
    )
    # A small dark box where the camera hangs (visual only, out of its own view).
    spec.worldbody.add_geom(
        name="top_cam_body",
        type=mujoco.mjtGeom.mjGEOM_BOX,
        pos=(TOP_POS + [0.02, 0, 0.02]).tolist(),
        size=[0.02, 0.03, 0.015],
        rgba=[0.12, 0.12, 0.12, 1],
        contype=0,
        conaffinity=0,
        group=2,
    )
    return spec


def build_model(profile: dict | None = None, size: float = CUBE_SIZE) -> mujoco.MjModel:
    return build_spec(profile, size).compile()


def cube_size(model) -> float:
    return float(model.geom(f"cube_{COLORS[0]}").size[0] * 2)


# ---- ground truth: scene setup and the referee only, never the stacker ----
def place_cube(model, data, color: str, x: float, y: float, yaw: float = 0.0, z=None):
    j = model.joint(f"cube_{color}")
    adr, vadr = model.jnt_qposadr[j.id], model.jnt_dofadr[j.id]
    zc = cube_size(model) / 2 + 1e-4 if z is None else z
    data.qpos[adr : adr + 3] = [x, y, zc]
    data.qpos[adr + 3 : adr + 7] = [math.cos(yaw / 2), 0, 0, math.sin(yaw / 2)]
    data.qvel[vadr : vadr + 6] = 0


def cube_pose(model, data, color: str) -> tuple[np.ndarray, float]:
    body = model.body(f"cube_{color}").id
    rot = data.xmat[body].reshape(3, 3)
    return data.xpos[body].copy(), math.atan2(rot[1, 0], rot[0, 0])


def random_layout(rng: np.random.Generator) -> dict[str, tuple[float, float, float]]:
    """Three spots in easy reach, centers at least MIN_GAP apart."""
    while True:
        spots = {c: base.random_cube_spot(rng) for c in COLORS}
        pts = [np.array(s[:2]) for s in spots.values()]
        if all(
            np.linalg.norm(pts[i] - pts[j]) >= MIN_GAP
            for i in range(3)
            for j in range(i + 1, 3)
        ):
            return spots


def place_layout(model, data, layout: dict) -> None:
    for color, (x, y, yaw) in layout.items():
        place_cube(model, data, color, x, y, yaw)
    mujoco.mj_forward(model, data)
