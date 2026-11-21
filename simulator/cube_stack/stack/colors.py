"""HSV color masks for the three cubes (OpenCV only, no learning).

Measured in the rendered scene (OpenCV hue 0~180): red cube 0~3, yellow cube
~28, blue cube ~114. The SO-101 model's printed parts are yellow too (hue
23~25), so the yellow band starts at 26 and the eyes also cut the robot out
(eye.py: a table region for the fixed camera, a jaw mask for the wrist).
"""

from __future__ import annotations

import cv2
import numpy as np

# (hue low, hue high) bands; red wraps around 0.
HSV = {
    "red": {"bands": [(0, 6), (170, 180)], "s": 120, "v": 70},
    "yellow": {"bands": [(26, 35)], "s": 120, "v": 70},
    "blue": {"bands": [(100, 128)], "s": 120, "v": 40},
}
# BGR for drawing.
DRAW = {"red": (40, 40, 255), "yellow": (0, 220, 255), "blue": (255, 120, 40)}
_KERNEL = np.ones((3, 3), np.uint8)


def mask(bgr: np.ndarray, color: str) -> np.ndarray:
    """uint8 0/255 mask of `color` in a BGR image."""
    t = HSV[color]
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    out = np.zeros(bgr.shape[:2], np.uint8)
    for lo, hi in t["bands"]:
        out |= cv2.inRange(
            hsv,
            np.array([lo, t["s"], t["v"]], np.uint8),
            np.array([hi, 255, 255], np.uint8),
        )
    out = cv2.morphologyEx(out, cv2.MORPH_OPEN, _KERNEL, iterations=1)
    return cv2.morphologyEx(out, cv2.MORPH_CLOSE, _KERNEL, iterations=2)


def saturated(bgr: np.ndarray, s_low=90, v_low=40) -> np.ndarray:
    """Any strongly colored pixel (used to learn where the robot shows up)."""
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    return ((hsv[..., 1] >= s_low) & (hsv[..., 2] >= v_low)).astype(np.uint8) * 255
