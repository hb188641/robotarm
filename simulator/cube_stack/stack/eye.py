"""Cameras that find colored cubes and turn pixels into table coordinates.

Both cameras' poses are known exactly in simulation (the fixed one would be
calibrated once on a real table), so each silhouette pixel is cast as a ray
onto a horizontal plane: the cube's mid-height for a cube on the table,
(n + 0.5) cube sizes up for one sitting on n others. The mean of those points
is the cube center; the minimum-area rectangle of the cast outline gives yaw.

    FixedEye  "top" camera in the air: sees the whole work area at once.
              Pixels landing within ROBOT_RADIUS of the base are ignored.
    WristEye  camera on the gripper: close-up correction before each grasp and
              checks of the tower. The jaws (yellow!) are cut out with masks
              learned once with nothing in view (`calibrate`).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import cv2
import mujoco
import numpy as np

from TITI.voice_motor import vision

from . import colors

ROBOT_RADIUS = 0.11  # m: the parked arm's base and shadow stay inside this


@dataclass
class Sighting:
    color: str
    x: float  # m, base frame, on the plane it was cast to
    y: float
    yaw: float  # radians, folded to -45°~45°
    pixel: tuple[float, float]  # silhouette centroid, 0~1
    area: float  # frame fraction


class Eye:
    min_area = 0.0002
    max_area = 0.05
    min_solidity = 0.75

    def __init__(self, model: mujoco.MjModel, camera: str, width=640, height=480):
        self.m = model
        self.cam = model.camera(camera).id
        self.width, self.height = width, height
        self.renderer = mujoco.Renderer(model, height, width)
        self.last_view: np.ndarray | None = None  # RGB with detections drawn

    def close(self) -> None:
        self.renderer.close()

    def capture(self, data) -> np.ndarray:
        self.renderer.update_scene(data, self.cam)
        return self.renderer.render().copy()

    def rays(self, data, pixels) -> tuple[np.ndarray, np.ndarray]:
        pixels = np.asarray(pixels, float)
        fovy = math.radians(self.m.cam_fovy[self.cam])
        f = (self.height / 2) / math.tan(fovy / 2)
        u = pixels[:, 0] + 0.5 - self.width / 2
        v = pixels[:, 1] + 0.5 - self.height / 2
        local = np.column_stack([u / f, -v / f, -np.ones(len(pixels))])
        rot = data.cam_xmat[self.cam].reshape(3, 3)
        return data.cam_xpos[self.cam].copy(), np.einsum("ij,kj->ik", local, rot)

    def to_plane(self, data, pixels, z: float) -> np.ndarray:
        origin, dirs = self.rays(data, pixels)
        with np.errstate(divide="ignore", invalid="ignore"):
            t = (z - origin[2]) / dirs[:, 2]
        t[~np.isfinite(t) | (t < 0)] = np.nan
        return origin + dirs * t[:, None]

    # ---- hooks ----
    def ignore(self, data, rgb) -> np.ndarray | None:
        """bool image of pixels that belong to the robot (never a cube)."""
        return None

    # ---- detection ----
    def color_mask(self, data, rgb, color) -> np.ndarray:
        m = colors.mask(cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), color)
        drop = self.ignore(data, rgb)
        if drop is not None:
            m[drop] = 0
        return m

    def find(self, data, color: str, plane_z: float, rgb=None, near=None, view=None):
        """The best `color` cube cast onto `plane_z`, or None.

        `near` = (x, y, radius): keep only blobs whose center lands there.
        """
        rgb = self.capture(data) if rgb is None else rgb
        m = self.color_mask(data, rgb, color)
        contours, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        frame = self.width * self.height
        best = None
        for c in contours:
            area = vision.cube_like(
                c, frame, self.min_area, self.max_area, self.min_solidity
            )
            if area is None:
                continue
            s = self._sighting(data, color, c, m.shape, plane_z, area)
            if s is None:
                continue
            if near is not None and math.hypot(s.x - near[0], s.y - near[1]) > near[2]:
                continue
            if best is None or area > best[0].area:
                best = (s, c)
        if view is not None and best is not None:
            s, c = best
            cv2.drawContours(view, [c], -1, colors.DRAW[color][::-1], 2)
            cx, cy = int(s.pixel[0] * self.width), int(s.pixel[1] * self.height)
            cv2.drawMarker(view, (cx, cy), (255, 255, 255), cv2.MARKER_CROSS, 14, 2)
        return best[0] if best else None

    def find_all(self, data, plane_z: float, names=colors.HSV) -> dict:
        rgb = self.capture(data)
        view = rgb.copy()
        found = {c: self.find(data, c, plane_z, rgb, view=view) for c in names}
        self.last_view = view
        return {c: s for c, s in found.items() if s is not None}

    def _sighting(self, data, color, contour, shape, plane_z, area):
        filled = np.zeros(shape, np.uint8)
        cv2.drawContours(filled, [contour], -1, 255, cv2.FILLED)
        vs, us = np.nonzero(filled)
        pts = self.to_plane(data, np.column_stack([us, vs]), plane_z)[:, :2]
        if np.isnan(pts).any():
            return None
        center = pts.mean(axis=0)
        outline = self.to_plane(data, contour[:, 0, :], plane_z)[:, :2]
        (_, _), (_, _), angle = cv2.minAreaRect((outline * 1000).astype(np.float32))
        yaw = math.radians(vision.fold_angle(angle))
        mo = cv2.moments(contour)
        cx, cy = mo["m10"] / mo["m00"], mo["m01"] / mo["m00"]
        return Sighting(
            color,
            float(center[0]),
            float(center[1]),
            yaw,
            (cx / self.width, cy / self.height),
            area,
        )


class FixedEye(Eye):
    """The camera hanging above the table. Use it with the arm parked."""

    max_area = 0.02

    def __init__(self, model, camera="top", width=640, height=480):
        super().__init__(model, camera, width, height)
        self._robot = None

    def ignore(self, data, rgb):
        if self._robot is None:  # the camera never moves: compute once
            vs, us = np.mgrid[0 : self.height, 0 : self.width]
            pts = self.to_plane(data, np.column_stack([us.ravel(), vs.ravel()]), 0.0)
            r = np.hypot(pts[:, 0], pts[:, 1])
            self._robot = (np.isnan(r) | (r < ROBOT_RADIUS)).reshape(
                self.height, self.width
            )
        return self._robot


class WristEye(Eye):
    """The gripper camera; `calibrate` learns where the jaws show up."""

    max_area = 0.4
    min_area = 0.0005

    def __init__(self, model, camera="wrist", width=480, height=360):
        super().__init__(model, camera, width, height)
        self.jaw_masks: list[tuple[float, np.ndarray]] = []  # (gripper q, bool mask)
        self.gripper_q = None  # callable → current gripper angle

    def learn_jaws(self, data, gripper_q: float) -> None:
        """Call with nothing colorful in view (the camera looking at the sky):
        every saturated pixel is part of the robot."""
        rgb = self.capture(data)
        m = colors.saturated(cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
        m = cv2.dilate(m, np.ones((9, 9), np.uint8)) > 0
        self.jaw_masks.append((gripper_q, m))

    def ignore(self, data, rgb):
        if not self.jaw_masks or self.gripper_q is None:
            return None
        q = self.gripper_q()
        ranked = sorted(self.jaw_masks, key=lambda e: abs(e[0] - q))
        out = ranked[0][1].copy()
        if len(ranked) > 1:  # between two learned openings: cut both
            out |= ranked[1][1]
        return out

    def color_pixels(self, data, color) -> np.ndarray:
        """bool image of `color` right now (jaws cut out), drawn into last_view."""
        rgb = self.capture(data)
        m = self.color_mask(data, rgb, color)
        view = rgb.copy()
        contours, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(view, contours, -1, colors.DRAW[color][::-1], 2)
        self.last_view = view
        return m > 0

    def look(self, data, color, plane_z, near=None):
        rgb = self.capture(data)
        view = rgb.copy()
        s = self.find(data, color, plane_z, rgb, near=near, view=view)
        self.last_view = view
        return s


def overlap(a: np.ndarray, b: np.ndarray) -> float:
    union = np.logical_or(a, b).sum()
    return float(np.logical_and(a, b).sum() / union) if union else 0.0
