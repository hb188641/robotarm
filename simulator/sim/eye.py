"""The wrist camera: render the first-person view and locate the red cube.

Detection reuses `TITI/voice_motor/vision.py` (the same HSV mask and cube-shape
test the real pick uses). Because the camera's pose is known exactly in
simulation, every silhouette pixel is cast as a ray onto the plane halfway up
the cube; the mean of those points is the cube center and their minimum-area
rectangle gives its yaw.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import cv2
import mujoco
import numpy as np

from TITI.voice_motor import vision

CAMERA = "wrist"
# The cube fills much more of a wrist camera's frame than of the MacBook's.
MAX_AREA = 0.4


@dataclass
class Sighting:
    x: float  # cube center on the table (m, base frame)
    y: float
    yaw: float  # cube edge heading (radians, folded to -45°~45°)
    pixel: tuple[float, float]  # silhouette centroid, 0~1
    area: float  # frame fraction


class WristEye:
    def __init__(self, model: mujoco.MjModel, width=480, height=360, hsv=None):
        self.m = model
        self.width, self.height = width, height
        self.hsv = hsv
        self.cam = model.camera(CAMERA).id
        self.renderer = mujoco.Renderer(model, height, width)
        self.last_view: np.ndarray | None = None  # RGB with the detection drawn

    def close(self) -> None:
        self.renderer.close()

    def capture(self, data: mujoco.MjData) -> np.ndarray:
        self.renderer.update_scene(data, self.cam)
        return self.renderer.render().copy()

    def _rays(self, data, pixels: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """World-frame origin and ray directions through (u, v) pixel centers."""
        fovy = math.radians(self.m.cam_fovy[self.cam])
        f = (self.height / 2) / math.tan(fovy / 2)
        u = pixels[:, 0] + 0.5 - self.width / 2
        v = pixels[:, 1] + 0.5 - self.height / 2
        local = np.column_stack([u / f, -v / f, -np.ones(len(pixels))])
        rot = data.cam_xmat[self.cam].reshape(3, 3)
        # einsum, not @: macOS Accelerate matmul raises spurious FP warnings here.
        return data.cam_xpos[self.cam].copy(), np.einsum("ij,kj->ik", local, rot)

    def to_table(self, data, pixels: np.ndarray, plane_z: float) -> np.ndarray:
        origin, dirs = self._rays(data, np.asarray(pixels, float))
        t = (plane_z - origin[2]) / dirs[:, 2]
        return origin + dirs * t[:, None]

    def find_cube(self, data: mujoco.MjData, cube_size: float) -> Sighting | None:
        rgb = self.capture(data)
        bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        mask = vision.red_mask(bgr, self.hsv)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        frame = self.width * self.height
        best, best_area = None, 0.0
        for c in contours:
            area = vision.cube_like(
                c, frame, 0.0005, MAX_AREA, vision.DEFAULT_MIN_SOLIDITY
            )
            if area is not None and area > best_area:
                best, best_area = c, area
        view = rgb.copy()
        if best is None:
            self.last_view = view
            return None

        # Every pixel inside the silhouette, cast onto the cube's mid-height plane.
        filled = np.zeros_like(mask)
        cv2.drawContours(filled, [best], -1, 255, cv2.FILLED)
        vs, us = np.nonzero(filled)
        pts = self.to_table(data, np.column_stack([us, vs]), cube_size / 2)
        center = pts[:, :2].mean(axis=0)
        outline = self.to_table(data, best[:, 0, :], cube_size / 2)[:, :2]
        (_, _), (_, _), angle = cv2.minAreaRect((outline * 1000).astype(np.float32))
        yaw = math.radians(vision.fold_angle(angle))

        m = cv2.moments(best)
        cx, cy = m["m10"] / m["m00"], m["m01"] / m["m00"]
        cv2.drawContours(view, [best], -1, (40, 255, 40), 2)
        cv2.drawMarker(view, (int(cx), int(cy)), (40, 255, 40), cv2.MARKER_CROSS, 18, 2)
        self.last_view = view
        return Sighting(
            float(center[0]),
            float(center[1]),
            yaw,
            (cx / self.width, cy / self.height),
            best_area,
        )
