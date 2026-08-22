from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Tuple

LEFT_SHOULDER_IDX = 11
RIGHT_SHOULDER_IDX = 12
RIGHT_ELBOW_IDX = 14
RIGHT_WRIST_IDX = 16
RIGHT_HIP_IDX = 24


@dataclass
class Point3:
    x: float
    y: float
    z: float


def _angle_between_2d(v1: Tuple[float, float], v2: Tuple[float, float]) -> float:
    dot = v1[0] * v2[0] + v1[1] * v2[1]
    n1 = math.hypot(*v1)
    n2 = math.hypot(*v2)
    if n1 == 0.0 or n2 == 0.0:
        return 0.0
    cos_theta = max(-1.0, min(1.0, dot / (n1 * n2)))
    return math.degrees(math.acos(cos_theta))


def compute_yaw_deg(left_shoulder: Point3, right_shoulder: Point3) -> float:
    """어깨선이 카메라 정면 대비 얼마나 회전했는지(도). 정면=0, z는 노이즈가 있어 스무딩 필요."""
    vx = right_shoulder.x - left_shoulder.x
    vz = right_shoulder.z - left_shoulder.z
    return math.degrees(math.atan2(vz, vx))


def compute_shoulder_lift_deg(shoulder: Point3, elbow: Point3, hip: Point3) -> float:
    """0=팔이 몸통(엉덩이 방향)과 같은 방향으로 늘어뜨림, 180=반대 방향(위)으로 뻗음."""
    v_down = (hip.x - shoulder.x, hip.y - shoulder.y)
    v_arm = (elbow.x - shoulder.x, elbow.y - shoulder.y)
    return _angle_between_2d(v_down, v_arm)


def compute_elbow_flex_deg(shoulder: Point3, elbow: Point3, wrist: Point3) -> float:
    """0=팔을 완전히 폄, 커질수록 팔꿈치가 굽음."""
    v1 = (shoulder.x - elbow.x, shoulder.y - elbow.y)
    v2 = (wrist.x - elbow.x, wrist.y - elbow.y)
    return 180.0 - _angle_between_2d(v1, v2)


class EmaFilter:
    """지수이동평균. 첫 update()는 그대로 반환, 이후는 alpha 비율로 새 값을 반영."""

    def __init__(self, alpha: float = 0.3):
        self.alpha = alpha
        self._value: Optional[float] = None

    def update(self, new_value: float) -> float:
        if self._value is None:
            self._value = new_value
        else:
            self._value = self.alpha * new_value + (1 - self.alpha) * self._value
        return self._value

    def reset(self) -> None:
        self._value = None
