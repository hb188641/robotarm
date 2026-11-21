"""Grade a stack from the physics ground truth. Never imported by the stacker."""

from __future__ import annotations

import math

from . import scene

XY_TOL = 0.006
Z_TOL = 0.004
YAW_TOL = math.radians(10)


def grade(model, data, order) -> dict:
    s = scene.cube_size(model)
    poses = [scene.cube_pose(model, data, c) for c in order]
    report = {"stacked": True, "layers": []}
    for k, (p, yaw) in enumerate(poses):
        z_ok = abs(p[2] - (k + 0.5) * s) <= Z_TOL
        if k == 0:
            xy = 0.0
            dyaw = 0.0
        else:
            below, byaw = poses[k - 1]
            xy = math.hypot(p[0] - below[0], p[1] - below[1])
            dyaw = abs((yaw - byaw + math.pi / 4) % (math.pi / 2) - math.pi / 4)
        ok = z_ok and xy <= XY_TOL and dyaw <= YAW_TOL
        report["layers"].append(
            {
                "color": order[k],
                "z_mm": p[2] * 1000,
                "offset_mm": xy * 1000,
                "yaw_deg": math.degrees(dyaw),
                "ok": ok,
            }
        )
        report["stacked"] &= ok
    return report
