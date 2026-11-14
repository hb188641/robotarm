"""SO-101 MuJoCo model with the robot_arm_app conventions (raw ticks 0~4095).

The model is TheRobotStudio's `so101_new_calib.xml`, the same geometry as the
URDF `TITI/voice_motor/kinematics.py` was built from. Its joint zero is the
URDF zero, so for motor_1~5:

    qpos = (tick - 2048) * 2π / 4096        (positive in the URDF direction)

The gripper (motor_6) is a linear map between the measured closed and open
ticks and the model's jaw angles, because its servo zero is not the jaw zero.

    build_model(profile)        → mujoco.MjModel (floor, grasp site, ranges)
    set_ticks(model, data, t)   → write ticks into data.qpos
    get_ticks(model, data)      → read data.qpos back as ticks
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import mujoco
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
MODEL_XML = ROOT / "models" / "so101" / "so101_new_calib.xml"
REPO = ROOT.parent
DEFAULT_PROFILE = REPO / "TITI" / "voice_motor" / "arm.json"

TICKS = 4096
CENTER = 2048
RAD_PER_TICK = 2 * math.pi / TICKS
MOTORS = ("motor_1", "motor_2", "motor_3", "motor_4", "motor_5", "motor_6")
JOINTS = {
    "motor_1": "shoulder_pan",
    "motor_2": "shoulder_lift",
    "motor_3": "elbow_flex",
    "motor_4": "wrist_flex",
    "motor_5": "wrist_roll",
    "motor_6": "gripper",
}
ARM = MOTORS[:5]

# Gripper: measured ticks (arm.json motor_6 min/max, "open": +1) ↔ jaw angle.
# Jaw angles are the model's joint range ends: -0.1745 closed, 1.7453 open.
GRIPPER_CLOSED_TICK = 1634
GRIPPER_OPEN_TICK = 2793
GRIPPER_CLOSED_Q = -0.17453
GRIPPER_OPEN_Q = 1.74533

# kinematics.py's grasp point: on the wrist-roll axis, 98 mm out, z pointing
# out of the gripper (URDF rpy 0, π, 0 → quaternion w=0, y=1).
GRASP_POS = (0.0, -0.000218121, -0.0981274)
GRASP_QUAT = (0.0, 0.0, 1.0, 0.0)
# Hidden by default (cameras and the detector must not see a red dot);
# the mirror viewer turns this group on.
GRASP_SITE_GROUP = 4


def tick_to_q(motor: str, tick: float) -> float:
    if motor == "motor_6":
        frac = (tick - GRIPPER_CLOSED_TICK) / (GRIPPER_OPEN_TICK - GRIPPER_CLOSED_TICK)
        return GRIPPER_CLOSED_Q + frac * (GRIPPER_OPEN_Q - GRIPPER_CLOSED_Q)
    return (tick - CENTER) * RAD_PER_TICK


def q_to_tick(motor: str, q: float) -> int:
    if motor == "motor_6":
        frac = (q - GRIPPER_CLOSED_Q) / (GRIPPER_OPEN_Q - GRIPPER_CLOSED_Q)
        tick = GRIPPER_CLOSED_TICK + frac * (GRIPPER_OPEN_TICK - GRIPPER_CLOSED_TICK)
    else:
        tick = CENTER + q / RAD_PER_TICK
    return int(min(max(round(tick), 0), TICKS - 1))


def tick_limits(profile: dict | None) -> dict[str, tuple[int, int]]:
    """{motor: (min, max)} measured ticks, for kinematics.solve(limits=...)."""
    out = {}
    for motor, cfg in ((profile or {}).get("joints") or {}).items():
        if cfg.get("min") is not None and cfg.get("max") is not None:
            out[motor] = (int(cfg["min"]), int(cfg["max"]))
    return out


def load_profile(path: Path | str | None = DEFAULT_PROFILE) -> dict | None:
    """voice_motor arm.json (measured joint min/max ticks), or None if absent."""
    if path is None or not Path(path).exists():
        return None
    return json.loads(Path(path).read_text(encoding="utf-8"))


def measured_ranges(profile: dict | None) -> dict[str, tuple[float, float]]:
    """{joint name: (low, high) radians} from measured tick limits."""
    out = {}
    for motor, cfg in ((profile or {}).get("joints") or {}).items():
        if motor not in JOINTS or cfg.get("min") is None or cfg.get("max") is None:
            continue
        a, b = tick_to_q(motor, cfg["min"]), tick_to_q(motor, cfg["max"])
        out[JOINTS[motor]] = (min(a, b), max(a, b))
    return out


def build_spec(profile: dict | None = None, floor: bool = True) -> mujoco.MjSpec:
    spec = mujoco.MjSpec.from_file(str(MODEL_XML))
    spec.modelname = "so101_sim"

    grip = spec.body("gripper")
    grip.add_site(
        name="grasp",
        pos=GRASP_POS,
        quat=GRASP_QUAT,
        size=[0.004, 0, 0],
        rgba=[1, 0.2, 0.2, 1],
        group=GRASP_SITE_GROUP,
    )

    # The CAD ranges are a little narrower than the real arm (measured motor_1
    # reaches 3426 ticks = 120°). Widen joint and actuator ranges to cover both,
    # so mirrored poses and commands are not clipped by the model.
    for name, (lo, hi) in measured_ranges(profile).items():
        joint = spec.joint(name)
        joint.range = [min(joint.range[0], lo), max(joint.range[1], hi)]
        act = spec.actuator(name)
        act.ctrlrange = [min(act.ctrlrange[0], lo), max(act.ctrlrange[1], hi)]

    if floor:
        tex = spec.add_texture(
            name="grid",
            type=mujoco.mjtTexture.mjTEXTURE_2D,
            builtin=mujoco.mjtBuiltin.mjBUILTIN_CHECKER,
            mark=mujoco.mjtMark.mjMARK_EDGE,
            rgb1=[0.72, 0.70, 0.66],
            rgb2=[0.64, 0.62, 0.58],
            markrgb=[0.6, 0.58, 0.55],
            width=300,
            height=300,
        )
        mat = spec.add_material(name="table", texrepeat=[20, 20], texuniform=True)
        mat.textures[mujoco.mjtTextureRole.mjTEXROLE_RGB] = tex.name
        spec.worldbody.add_geom(
            name="table",
            type=mujoco.mjtGeom.mjGEOM_PLANE,
            size=[0.6, 0.6, 0.01],
            material="table",
        )
        spec.worldbody.add_light(
            pos=[0.3, -0.3, 1.2], dir=[-0.3, 0.3, -1], diffuse=[0.45] * 3
        )
    spec.visual.headlight.ambient = [0.3] * 3
    spec.visual.headlight.diffuse = [0.3] * 3
    spec.visual.global_.azimuth = 150
    spec.visual.global_.elevation = -25
    spec.visual.global_.offwidth = 1280
    spec.visual.global_.offheight = 960
    spec.stat.center = [0.15, 0.0, 0.12]
    spec.stat.extent = 0.45
    return spec


def build_model(profile: dict | None = None, floor: bool = True) -> mujoco.MjModel:
    return build_spec(profile, floor).compile()


def _qpos_adr(model: mujoco.MjModel, motor: str) -> int:
    return model.jnt_qposadr[model.joint(JOINTS[motor]).id]


def set_ticks(model: mujoco.MjModel, data: mujoco.MjData, ticks: dict) -> None:
    """Write raw ticks (any subset of motor_1~6) into data.qpos and data.ctrl."""
    for motor, tick in ticks.items():
        if motor not in JOINTS:
            continue
        q = tick_to_q(motor, tick)
        data.qpos[_qpos_adr(model, motor)] = q
        data.ctrl[model.actuator(JOINTS[motor]).id] = q


def get_ticks(model: mujoco.MjModel, data: mujoco.MjData) -> dict[str, int]:
    return {m: q_to_tick(m, data.qpos[_qpos_adr(model, m)]) for m in MOTORS}


def grasp_pose(model: mujoco.MjModel, data: mujoco.MjData) -> np.ndarray:
    """4x4 pose of the grasp site (after mj_kinematics / mj_forward)."""
    site = model.site("grasp").id
    pose = np.eye(4)
    pose[:3, :3] = data.site_xmat[site].reshape(3, 3)
    pose[:3, 3] = data.site_xpos[site]
    return pose
