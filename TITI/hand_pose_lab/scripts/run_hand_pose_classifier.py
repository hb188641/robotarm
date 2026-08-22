from __future__ import annotations

import argparse
import sys
import threading
import time
from pathlib import Path

import cv2
import torch

from hand_common import (
    DEFAULT_MODEL_PATH,
    HAND_LANDMARKER_MODEL_PATH,
    LABEL_DISPLAY_KO,
    create_hand_landmarker,
    detect_hand,
    draw_hand,
    draw_text_panel,
    landmarks_to_vector,
    open_camera,
    resize_for_display,
)
from tiny_hand_policy import load_policy_checkpoint, select_device

# TITI/hand_pose_lab/scripts/ -> TITI/ -> TITI/robot_arm_app (클라이언트.py가 있는 곳)
ROBOT_ARM_APP_DIR = Path(__file__).resolve().parent.parent.parent / "robot_arm_app"
sys.path.append(str(ROBOT_ARM_APP_DIR))
from 클라이언트 import 로봇팔

CONFIDENCE_THRESHOLD = 0.7  # 이 값보다 확신도가 낮으면 open/closed 콜백을 호출하지 않음

팔 = 로봇팔()
팔.토크켜기()

def on_open() -> None:
    팔.놓기()


def on_closed() -> None:
    팔.잡기()
    print("closed")


ON_LABEL_CALLBACKS = {"open": on_open, "closed": on_closed}


def trigger_callback(label: str) -> None:
    """API 호출(팔.놓기()/팔.잡기())은 네트워크 왕복이 있어 느리므로,
    카메라 루프를 막지 않도록 별도 스레드에서 실행."""
    callback = ON_LABEL_CALLBACKS.get(label)
    if callback is not None:
        threading.Thread(target=callback, daemon=True).start()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="학습된 모델로 손 펴짐/접힘을 실시간 추론.")
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_MODEL_PATH)
    parser.add_argument("--model", type=Path, default=HAND_LANDMARKER_MODEL_PATH, help="hand_landmarker.task 경로.")
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
    window_name = "Hand pose classifier"
    current_state = None  # 마지막으로 콜백을 트리거한 라벨 (상태 변화 감지용)

    print("q 또는 ESC로 종료")
    with create_hand_landmarker(args.model) as detector:
        try:
            while True:
                ok, frame = cap.read()
                if not ok or frame is None:
                    print("Frame read failed.")
                    break

                frame = cv2.flip(frame, 1)
                timestamp_ms = int(time.monotonic() * 1000)
                hand = detect_hand(detector, frame, timestamp_ms)

                display = frame.copy()
                lines = ["Hand pose classifier"]

                if hand is not None:
                    draw_hand(display, hand)
                    vector = landmarks_to_vector(hand)
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
                    lines.append("손이 감지되지 않음")

                draw_text_panel(display, lines)
                cv2.imshow(window_name, resize_for_display(display, args.display_width))
                key = cv2.waitKey(1) & 0xFF
                if key in (ord("q"), 27):
                    break
        finally:
            팔.토크끄기()
            cap.release()
            cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
