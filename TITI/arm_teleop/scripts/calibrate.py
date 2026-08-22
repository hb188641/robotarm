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
from pose_common import (  # noqa: E402
    create_pose_landmarker,
    detect_pose,
    draw_pose,
    draw_text_panel,
    open_camera,
    resize_for_display,
)

ROBOT_ARM_APP_DIR = Path(__file__).resolve().parent.parent.parent / "robot_arm_app"
sys.path.append(str(ROBOT_ARM_APP_DIR))
from 클라이언트 import 로봇팔  # noqa: E402

CALIBRATION_PATH = Path(__file__).resolve().parent.parent / "calibration.json"
WINDOW_NAME = "Calibrate"

STEPS = ["motor_1", "motor_2", "motor_3"]

SPACE_KEY = 32
ESC_KEY = 27


class CalibrationCancelled(Exception):
    pass


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


def _live_capture(cap, detector, display_width: int, prompt: str) -> dict:
    """실시간 카메라 미리보기 + pose 오버레이를 보여주다가, 스페이스바를 누르는 순간의
    사람 각도(dict)를 반환. ESC를 누르면 CalibrationCancelled를 발생시킨다."""
    while True:
        ok, frame = cap.read()
        if not ok or frame is None:
            continue

        frame = cv2.flip(frame, 1)
        timestamp_ms = int(time.monotonic() * 1000)
        pose = detect_pose(detector, frame, timestamp_ms)

        display = frame.copy()
        lines = [prompt, "스페이스바: 이 자세로 기록 / ESC: 취소"]

        angles = None
        if pose is not None:
            draw_pose(display, pose)
            angles = _human_angles(pose)
            lines.append(f"motor_1 (yaw): {angles['motor_1']:.1f} deg")
            lines.append(f"motor_2 (shoulder): {angles['motor_2']:.1f} deg")
            lines.append(f"motor_3 (elbow): {angles['motor_3']:.1f} deg")
        else:
            lines.append("사람이 감지되지 않음")

        draw_text_panel(display, lines)
        cv2.imshow(WINDOW_NAME, resize_for_display(display, display_width))

        key = cv2.waitKey(1) & 0xFF
        if key == ESC_KEY:
            raise CalibrationCancelled()
        if key == SPACE_KEY and angles is not None:
            return angles


def main() -> None:
    parser = argparse.ArgumentParser(description="motor_1~3용 2점 캘리브레이션.")
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--display-width", type=int, default=1280)
    args = parser.parse_args()

    arm = 로봇팔()
    arm.토크끄기()  # 캘리브레이션 중에는 손으로 직접 팔을 움직여야 하므로 토크를 끈다.

    cap = open_camera(args.camera, 1280, 720, 30)
    result: dict = {}
    print("각 단계마다: 사람과 로봇팔을 동시에 해당 자세로 맞춘 뒤, 카메라 창에서 스페이스바를 누르세요.")
    try:
        with create_pose_landmarker() as detector:
            for motor in STEPS:
                angles = _live_capture(
                    cap, detector, args.display_width, f"[{motor}] 첫 번째 기준 자세로 맞추세요"
                )
                deg_a = angles[motor]
                raw_a = arm.위치(motor)
                print(f"  [{motor}] 첫 번째 자세 기록: human_deg={deg_a:.1f}, raw={raw_a}")

                angles = _live_capture(
                    cap, detector, args.display_width, f"[{motor}] 두 번째 기준 자세로 맞추세요"
                )
                deg_b = angles[motor]
                raw_b = arm.위치(motor)
                print(f"  [{motor}] 두 번째 자세 기록: human_deg={deg_b:.1f}, raw={raw_b}")

                yaw_zero = 0.0
                if motor == "motor_1":
                    angles = _live_capture(
                        cap, detector, args.display_width, "[motor_1] 카메라를 정면으로 보고 서세요 (yaw 0점 기준)"
                    )
                    yaw_zero = angles[motor]
                    print(f"  [motor_1] yaw 0점 기록: {yaw_zero:.1f}")

                result[motor] = MotorCalibration(
                    human_deg_a=deg_a, raw_a=raw_a, human_deg_b=deg_b, raw_b=raw_b, yaw_zero=yaw_zero
                )
    except CalibrationCancelled:
        print("\nESC로 취소되어 calibration.json을 저장하지 않았습니다.")
        return
    finally:
        cap.release()
        cv2.destroyAllWindows()

    save_calibration(CALIBRATION_PATH, result)
    print(f"\n캘리브레이션 저장 완료: {CALIBRATION_PATH}")


if __name__ == "__main__":
    main()
