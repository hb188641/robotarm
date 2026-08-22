from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import cv2

sys.path.append(str(Path(__file__).resolve().parent))
from teleop_common import (
    MotorCalibration,
    Point3,
    RIGHT_ELBOW_IDX,
    RIGHT_HIP_IDX,
    RIGHT_SHOULDER_IDX,
    RIGHT_WRIST_IDX,
    LEFT_SHOULDER_IDX,
    compute_elbow_flex_deg,
    compute_shoulder_lift_deg,
    compute_yaw_deg,
    save_calibration,
)

ARM_POSE_LAB_SCRIPTS = Path(__file__).resolve().parent.parent.parent / "arm_pose_lab" / "scripts"
sys.path.append(str(ARM_POSE_LAB_SCRIPTS))
from pose_common import create_pose_landmarker, detect_pose, open_camera  # noqa: E402

ROBOT_ARM_APP_DIR = Path(__file__).resolve().parent.parent.parent / "robot_arm_app"
sys.path.append(str(ROBOT_ARM_APP_DIR))
from 클라이언트 import 로봇팔  # noqa: E402

CALIBRATION_PATH = Path(__file__).resolve().parent.parent / "calibration.json"

STEPS = ["motor_1", "motor_2", "motor_3"]


def _human_angles(pose) -> dict:
    left_shoulder = Point3(pose[LEFT_SHOULDER_IDX].x, pose[LEFT_SHOULDER_IDX].y, pose[LEFT_SHOULDER_IDX].z)
    shoulder = Point3(pose[RIGHT_SHOULDER_IDX].x, pose[RIGHT_SHOULDER_IDX].y, pose[RIGHT_SHOULDER_IDX].z)
    elbow = Point3(pose[RIGHT_ELBOW_IDX].x, pose[RIGHT_ELBOW_IDX].y, pose[RIGHT_ELBOW_IDX].z)
    wrist = Point3(pose[RIGHT_WRIST_IDX].x, pose[RIGHT_WRIST_IDX].y, pose[RIGHT_WRIST_IDX].z)
    hip = Point3(pose[RIGHT_HIP_IDX].x, pose[RIGHT_HIP_IDX].y, pose[RIGHT_HIP_IDX].z)
    return {
        "motor_1": compute_yaw_deg(left_shoulder, shoulder),
        "motor_2": compute_shoulder_lift_deg(shoulder, elbow, hip),
        "motor_3": compute_elbow_flex_deg(shoulder, elbow, wrist),
    }


def _capture_reading(cap, detector) -> dict:
    """현재 프레임에서 pose를 감지할 때까지 몇 번 재시도 후 사람 각도 dict 반환."""
    for _ in range(30):
        ok, frame = cap.read()
        if not ok or frame is None:
            continue
        frame = cv2.flip(frame, 1)
        timestamp_ms = int(time.monotonic() * 1000)
        pose = detect_pose(detector, frame, timestamp_ms)
        cv2.imshow("Calibrate", frame)
        cv2.waitKey(1)
        if pose is not None:
            return _human_angles(pose)
        time.sleep(0.05)
    raise RuntimeError("사람 pose를 감지하지 못했습니다. 카메라 앞에 서 있는지 확인하세요.")


def main() -> None:
    parser = argparse.ArgumentParser(description="motor_1~3용 2점 캘리브레이션.")
    parser.add_argument("--camera", type=int, default=0)
    args = parser.parse_args()

    arm = 로봇팔()
    arm.토크끄기()  # 캘리브레이션 중에는 손으로 직접 팔을 움직여야 하므로 토크를 끈다.

    cap = open_camera(args.camera, 1280, 720, 30)
    result: dict = {}
    try:
        with create_pose_landmarker() as detector:
            for motor in STEPS:
                input(f"\n[{motor}] 첫 번째 기준 자세로 팔을 손으로 움직이고 Enter를 누르세요...")
                deg_a = _capture_reading(cap, detector)[motor]
                raw_a = arm.위치(motor)
                print(f"  기록: human_deg={deg_a:.1f}, raw={raw_a}")

                input(f"[{motor}] 두 번째 기준 자세로 팔을 손으로 움직이고 Enter를 누르세요...")
                deg_b = _capture_reading(cap, detector)[motor]
                raw_b = arm.위치(motor)
                print(f"  기록: human_deg={deg_b:.1f}, raw={raw_b}")

                yaw_zero = 0.0
                if motor == "motor_1":
                    input("[motor_1] 이제 카메라를 정면으로 보고 서서 Enter를 누르세요 (yaw 0점 기준)...")
                    yaw_zero = _capture_reading(cap, detector)[motor]

                result[motor] = MotorCalibration(
                    human_deg_a=deg_a, raw_a=raw_a, human_deg_b=deg_b, raw_b=raw_b, yaw_zero=yaw_zero
                )
    finally:
        cap.release()
        cv2.destroyAllWindows()

    save_calibration(CALIBRATION_PATH, result)
    print(f"\n캘리브레이션 저장 완료: {CALIBRATION_PATH}")


if __name__ == "__main__":
    main()
