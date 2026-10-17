from __future__ import annotations

from pathlib import Path
import sys

import cv2
import mediapipe as mp
import numpy as np

# Preserve direct execution from any working directory.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
# Re-export the original helper API for existing scripts.
from common.data import (
    ensure_dir as ensure_dir,
    timestamp_string as timestamp_string,
    write_json as write_json,
    read_csv_rows as read_csv_rows,
)
from common.vision import (
    open_camera as open_camera,
    draw_text_panel as draw_text_panel,
    resize_for_display as resize_for_display,
)

# scripts/hand_common.py -> scripts/ -> hand_pose_lab/ -> TITI/ -> 저장소 루트
# 어느 디렉터리에서 스크립트를 실행하든 항상 같은 data/, models/ 위치를 가리키도록 함
LAB_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = LAB_DIR.parent.parent
HAND_LANDMARKER_MODEL_PATH = REPO_ROOT / "hand_landmarker.task"
DEFAULT_DATASET_DIR = LAB_DIR / "data" / "hand_pose"
DEFAULT_MODEL_PATH = LAB_DIR / "models" / "hand_pose_classifier.pt"
DEFAULT_SUMMARY_PATH = LAB_DIR / "models" / "hand_pose_training_summary.json"


HAND_POSE_LABELS = ["open", "closed"]
LABEL_DISPLAY_KO = {"open": "펴짐", "closed": "접힘"}

LABEL_KEYS = {
    ord("o"): "open",
    ord("f"): "closed",
}

WRIST_IDX = 0
MIDDLE_MCP_IDX = 9  # 손목-이 랜드마크 거리를 스케일 기준으로 사용

CONNECTIONS = mp.tasks.vision.HandLandmarksConnections.HAND_CONNECTIONS


def create_hand_landmarker(model_path: Path = HAND_LANDMARKER_MODEL_PATH):
    options = mp.tasks.vision.HandLandmarkerOptions(
        base_options=mp.tasks.BaseOptions(model_asset_path=str(model_path)),
        running_mode=mp.tasks.vision.RunningMode.VIDEO,
        num_hands=1,
    )
    return mp.tasks.vision.HandLandmarker.create_from_options(options)


def detect_hand(detector, frame_bgr: np.ndarray, timestamp_ms: int):
    """frame(BGR)에서 첫 번째 손의 랜드마크 리스트(21개, .x/.y/.z)를 반환. 손이 없으면 None."""
    rgb_frame = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
    mp_image = mp.Image(mp.ImageFormat.SRGB, rgb_frame)
    result = detector.detect_for_video(mp_image, timestamp_ms)
    if not result.hand_landmarks:
        return None
    return result.hand_landmarks[0]


def draw_hand(frame: np.ndarray, hand) -> None:
    height, width = frame.shape[:2]
    points = []

    for landmark in hand:
        x = int(landmark.x * width)
        y = int(landmark.y * height)
        points.append((x, y))

    for line in CONNECTIONS:
        cv2.line(frame, points[line.start], points[line.end], (0, 220, 255), 2)

    for point in points:
        cv2.circle(frame, point, 5, (0, 70, 255), -1)


def landmarks_to_vector(hand) -> np.ndarray:
    """
    MediaPipe 21개 랜드마크(x,y,z)를 손목 기준 평행이동 + 스케일 정규화한 63차원 벡터로 변환.
    손이 화면 어디에 있든, 카메라와의 거리가 달라져도 같은 손모양이면 같은 벡터가 나오도록 만든다.
    """
    points = np.array([[lm.x, lm.y, lm.z] for lm in hand], dtype=np.float32)  # (21, 3)

    origin = points[WRIST_IDX]
    centered = points - origin

    scale = float(np.linalg.norm(centered[MIDDLE_MCP_IDX]))
    if scale < 1e-6:
        scale = 1e-6

    normalized = centered / scale
    return normalized.reshape(-1)  # (63,)
