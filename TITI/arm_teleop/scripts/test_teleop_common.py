import json
import math

from teleop_common import (
    EmaFilter,
    MotorCalibration,
    Point3,
    clamp_step,
    compute_elbow_flex_deg,
    compute_shoulder_lift_deg,
    compute_yaw_deg,
    load_calibration,
    save_calibration,
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


def test_human_deg_to_raw_linear_interpolation():
    cal = MotorCalibration(human_deg_a=0.0, raw_a=2048, human_deg_b=90.0, raw_b=3000)
    assert cal.human_deg_to_raw(45.0) == round(2048 + (3000 - 2048) * 0.5)


def test_human_deg_to_raw_clamps_below_range():
    cal = MotorCalibration(human_deg_a=0.0, raw_a=2048, human_deg_b=90.0, raw_b=3000)
    assert cal.human_deg_to_raw(-100.0) == 2048


def test_human_deg_to_raw_clamps_above_range():
    cal = MotorCalibration(human_deg_a=0.0, raw_a=2048, human_deg_b=90.0, raw_b=3000)
    assert cal.human_deg_to_raw(999.0) == 3000


def test_human_deg_to_raw_works_when_raw_b_less_than_raw_a():
    cal = MotorCalibration(human_deg_a=0.0, raw_a=3000, human_deg_b=90.0, raw_b=2048)
    assert cal.human_deg_to_raw(0.0) == 3000
    assert cal.human_deg_to_raw(90.0) == 2048
    # deg=999는 deg_b(90) 방향으로 더 간 값이라 raw_b 쪽 극단(2048)으로 클램프됨
    assert cal.human_deg_to_raw(999.0) == 2048


def test_save_and_load_calibration_roundtrip(tmp_path):
    calibration = {
        "motor_1": MotorCalibration(human_deg_a=0.0, raw_a=2048, human_deg_b=30.0, raw_b=2900, yaw_zero=1.5),
        "motor_2": MotorCalibration(human_deg_a=10.0, raw_a=1200, human_deg_b=150.0, raw_b=3400),
    }
    path = tmp_path / "calibration.json"
    save_calibration(path, calibration)

    loaded = load_calibration(path)

    assert loaded["motor_1"] == calibration["motor_1"]
    assert loaded["motor_2"] == calibration["motor_2"]
    assert json.loads(path.read_text(encoding="utf-8"))["motor_1"]["yaw_zero"] == 1.5


def test_clamp_step_passes_through_when_within_limit():
    assert clamp_step(current=2048, target=2060, max_delta=15) == 2060


def test_clamp_step_limits_large_positive_jump():
    assert clamp_step(current=2048, target=3000, max_delta=15) == 2063


def test_clamp_step_limits_large_negative_jump():
    assert clamp_step(current=2048, target=1000, max_delta=15) == 2033


def test_clamp_step_exact_limit_passes_through():
    assert clamp_step(current=2048, target=2063, max_delta=15) == 2063
