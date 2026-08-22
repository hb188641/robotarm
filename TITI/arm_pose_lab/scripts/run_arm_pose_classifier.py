from __future__ import annotations

import argparse
import sys
import threading
import time
from pathlib import Path

import cv2
import torch

from pose_common import (
    DEFAULT_MODEL_PATH,
    LABEL_DISPLAY_KO,
    POSE_LANDMARKER_MODEL_PATH,
    create_pose_landmarker,
    detect_pose,
    draw_pose,
    draw_text_panel,
    landmarks_to_vector,
    open_camera,
    resize_for_display,
)
from tiny_arm_policy import load_policy_checkpoint, select_device

# TITI/arm_pose_lab/scripts/ -> TITI/ -> TITI/robot_arm_app (클라이언트.py가 있는 곳)
ROBOT_ARM_APP_DIR = Path(__file__).resolve().parent.parent.parent / "robot_arm_app"
sys.path.append(str(ROBOT_ARM_APP_DIR))
from 클라이언트 import 로봇팔

CONFIDENCE_THRESHOLD = 0.6  # 이 값보다 확신도가 낮으면 extended/folded 콜백을 호출하지 않음

MOTOR_3_EXTENDED_POSITION = 2048  # 펴짐 판정 시 motor_3 목표
MOTOR_3_FOLDED_POSITION = 1300  # 접힘 판정 시 motor_3 목표 (arrow_key_control.py의 MOTOR_3_THRESHOLD와 동일)

팔 = 로봇팔()
팔.토크켜기()


def on_extended() -> None:
    팔.이동("motor_3", MOTOR_3_EXTENDED_POSITION)
    print("extended")


def on_folded() -> None:
    팔.이동("motor_3", MOTOR_3_FOLDED_POSITION)
    print("folded")


ON_LABEL_CALLBACKS = {"extended": on_extended, "folded": on_folded}


def trigger_callback(label: str) -> None:
    """API 호출은 네트워크 왕복이 있어 느리므로, 카메라 루프를 막지 않도록 별도 스레드에서 실행."""
    callback = ON_LABEL_CALLBACKS.get(label)
    if callback is not None:
        threading.Thread(target=callback, daemon=True).start()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="학습된 모델로 오른팔 펴짐/접힘을 실시간 추론해서 motor_3를 제어.")
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_MODEL_PATH)
    parser.add_argument("--model", type=Path, default=POSE_LANDMARKER_MODEL_PATH, help="pose_landmarker_full.task 경로.")
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--display-width", type=int, default=1280)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.checkpoint.exists():
        raise FileNotFoundError(f"Checkpoint not found: {args.checkpoint}")

    device = select_device()
    model, checkpoint = load_policy_checkpoint(args.checkpoint, device)
    label_names = checkpoint["label_names"]

    cap = open_camera(args.camera, args.width, args.height, args.fps)
    window_name = "Arm pose classifier"
    current_state = None  # 마지막으로 콜백을 트리거한 라벨 (상태 변화 감지용)

    print("q 또는 ESC로 종료")
    with create_pose_landmarker(args.model) as detector:
        try:
            while True:
                ok, frame = cap.read()
                if not ok or frame is None:
                    print("Frame read failed.")
                    break

                frame = cv2.flip(frame, 1)
                timestamp_ms = int(time.monotonic() * 1000)
                pose = detect_pose(detector, frame, timestamp_ms)

                display = frame.copy()
                lines = ["Arm pose classifier (right arm -> motor_3)"]

                if pose is not None:
                    draw_pose(display, pose)
                    vector = landmarks_to_vector(pose)
                    with torch.no_grad():
                        features = torch.from_numpy(vector).unsqueeze(0).to(device)
                        logits = model(features)
                        probs = torch.softmax(logits, dim=1)[0].detach().cpu()
                        pred_idx = int(torch.argmax(probs).item())
                        predicted_label = label_names[pred_idx]
                        confidence = float(probs[pred_idx].item())

                    lines.append(f"{LABEL_DISPLAY_KO.get(predicted_label, predicted_label)} ({confidence:.2f})")
                    for label, prob in zip(label_names, probs.tolist()):
                        lines.append(f"{LABEL_DISPLAY_KO.get(label, label)}: {prob:.2f}")

                    if (
                        confidence >= CONFIDENCE_THRESHOLD
                        and predicted_label in ON_LABEL_CALLBACKS
                        and predicted_label != current_state
                    ):
                        current_state = predicted_label
                        trigger_callback(predicted_label)
                else:
                    lines.append("사람이 감지되지 않음")

                draw_text_panel(display, lines)
                cv2.imshow(window_name, resize_for_display(display, args.display_width))
                key = cv2.waitKey(1) & 0xFF
                if key in (ord("q"), 27):
                    break
        finally:
            cap.release()
            cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
