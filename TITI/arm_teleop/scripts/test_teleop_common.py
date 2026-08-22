import math

from teleop_common import (
    EmaFilter,
    Point3,
    compute_elbow_flex_deg,
    compute_shoulder_lift_deg,
    compute_yaw_deg,
)


def test_yaw_zero_when_facing_camera():
    left = Point3(x=0.3, y=0.5, z=0.0)
    right = Point3(x=0.7, y=0.5, z=0.0)
    assert compute_yaw_deg(left, right) == 0.0


def test_yaw_positive_when_right_shoulder_closer_to_camera():
    left = Point3(x=0.3, y=0.5, z=0.0)
    right = Point3(x=0.6, y=0.5, z=-0.2)
    yaw = compute_yaw_deg(left, right)
    assert yaw < 0.0


def test_shoulder_lift_zero_when_arm_hangs_along_torso():
    hip = Point3(x=0.5, y=0.9, z=0.0)
    shoulder = Point3(x=0.5, y=0.3, z=0.0)
    elbow = Point3(x=0.5, y=0.6, z=0.0)
    deg = compute_shoulder_lift_deg(shoulder, elbow, hip)
    assert math.isclose(deg, 0.0, abs_tol=1e-6)


def test_shoulder_lift_180_when_arm_points_up():
    hip = Point3(x=0.5, y=0.9, z=0.0)
    shoulder = Point3(x=0.5, y=0.3, z=0.0)
    elbow = Point3(x=0.5, y=0.0, z=0.0)
    deg = compute_shoulder_lift_deg(shoulder, elbow, hip)
    assert math.isclose(deg, 180.0, abs_tol=1e-6)


def test_elbow_flex_zero_when_arm_straight():
    shoulder = Point3(x=0.5, y=0.3, z=0.0)
    elbow = Point3(x=0.5, y=0.6, z=0.0)
    wrist = Point3(x=0.5, y=0.9, z=0.0)
    deg = compute_elbow_flex_deg(shoulder, elbow, wrist)
    assert math.isclose(deg, 0.0, abs_tol=1e-6)


def test_elbow_flex_90_when_right_angle():
    shoulder = Point3(x=0.5, y=0.3, z=0.0)
    elbow = Point3(x=0.5, y=0.6, z=0.0)
    wrist = Point3(x=0.8, y=0.6, z=0.0)
    deg = compute_elbow_flex_deg(shoulder, elbow, wrist)
    assert math.isclose(deg, 90.0, abs_tol=1e-6)


def test_ema_first_update_returns_input_unchanged():
    f = EmaFilter(alpha=0.3)
    assert f.update(10.0) == 10.0


def test_ema_smooths_toward_new_value():
    f = EmaFilter(alpha=0.3)
    f.update(10.0)
    result = f.update(20.0)
    assert result == 0.3 * 20.0 + 0.7 * 10.0


def test_ema_reset_clears_state():
    f = EmaFilter(alpha=0.3)
    f.update(10.0)
    f.reset()
    assert f.update(5.0) == 5.0
