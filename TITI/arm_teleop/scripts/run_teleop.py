from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import cv2

sys.path.append(str(Path(__file__).resolve().parent))
from teleop_common import (
    EmaFilter,
    LEFT_SHOULDER_IDX,
    Point3,
    RIGHT_ELBOW_IDX,
    RIGHT_HIP_IDX,
    RIGHT_SHOULDER_IDX,
    RIGHT_WRIST_IDX,
    compute_elbow_flex_deg,
    compute_shoulder_lift_deg,
    compute_yaw_deg,
    load_calibration,
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="pose landmark로 motor_1~3 실시간 텔레옵.")
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--display-width", type=int, default=1280)
    parser.add_argument("--alpha", type=float, default=0.3, help="EMA 스무딩 계수 (0~1, 클수록 반응 빠르고 떨림 큼)")
    parser.add_argument("--dry-run", action="store_true", help="계산된 raw 값만 출력하고 실제 모터에는 보내지 않음")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not CALIBRATION_PATH.exists():
        raise FileNotFoundError(f"캘리브레이션 파일이 없습니다: {CALIBRATION_PATH}. 먼저 calibrate.py를 실행하세요.")
    calibration = load_calibration(CALIBRATION_PATH)

    filters = {motor: EmaFilter(alpha=args.alpha) for motor in ("motor_1", "motor_2", "motor_3")}

    arm = 로봇팔()
    if not args.dry_run:
        arm.토크켜기()

    cap = open_camera(args.camera, args.width, args.height, args.fps)
    window_name = "Arm teleop (motor_1~3)"

    print("q 또는 ESC로 종료")
    try:
        with create_pose_landmarker() as detector:
            while True:
                ok, frame = cap.read()
                if not ok or frame is None:
                    print("Frame read failed.")
                    break

                frame = cv2.flip(frame, 1)
                timestamp_ms = int(time.monotonic() * 1000)
                pose = detect_pose(detector, frame, timestamp_ms)

                display = frame.copy()
                lines = ["Arm teleop"]

                if pose is not None:
                    draw_pose(display, pose)

                    left_shoulder = Point3(pose[LEFT_SHOULDER_IDX].x, pose[LEFT_SHOULDER_IDX].y, pose[LEFT_SHOULDER_IDX].z)
                    shoulder = Point3(pose[RIGHT_SHOULDER_IDX].x, pose[RIGHT_SHOULDER_IDX].y, pose[RIGHT_SHOULDER_IDX].z)
                    elbow = Point3(pose[RIGHT_ELBOW_IDX].x, pose[RIGHT_ELBOW_IDX].y, pose[RIGHT_ELBOW_IDX].z)
                    wrist = Point3(pose[RIGHT_WRIST_IDX].x, pose[RIGHT_WRIST_IDX].y, pose[RIGHT_WRIST_IDX].z)
                    hip = Point3(pose[RIGHT_HIP_IDX].x, pose[RIGHT_HIP_IDX].y, pose[RIGHT_HIP_IDX].z)

                    raw_yaw = compute_yaw_deg(left_shoulder, shoulder) - calibration["motor_1"].yaw_zero
                    raw_shoulder = compute_shoulder_lift_deg(shoulder, elbow, hip)
                    raw_elbow = compute_elbow_flex_deg(shoulder, elbow, wrist)

                    smoothed = {
                        "motor_1": filters["motor_1"].update(raw_yaw),
                        "motor_2": filters["motor_2"].update(raw_shoulder),
                        "motor_3": filters["motor_3"].update(raw_elbow),
                    }

                    targets = {
                        motor: calibration[motor].human_deg_to_raw(deg) for motor, deg in smoothed.items()
                    }

                    for motor, deg in smoothed.items():
                        lines.append(f"{motor}: {deg:.1f} deg -> raw {targets[motor]}")

                    if args.dry_run:
                        print(targets)
                    else:
                        arm.여러개이동(targets)
                else:
                    lines.append("사람이 감지되지 않음")
                    for motor in filters.values():
                        motor.reset()

                draw_text_panel(display, lines)
                cv2.imshow(window_name, resize_for_display(display, args.display_width))
                key = cv2.waitKey(1) & 0xFF
                if key in (ord("q"), 27):
                    break
    finally:
        if not args.dry_run:
            arm.토크끄기()
        cap.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
