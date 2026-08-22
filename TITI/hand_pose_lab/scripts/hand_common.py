from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

import cv2
import mediapipe as mp
import numpy as np

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


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def timestamp_string() -> str:
    return time.strftime("%Y%m%d_%H%M%S")


def write_json(path: Path, payload: Dict) -> None:
    ensure_dir(path.parent)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def open_camera(camera_index: int, width: int, height: int, fps: int) -> cv2.VideoCapture:
    cap = cv2.VideoCapture(camera_index)
    if not cap.isOpened():
        raise RuntimeError(f"Camera index {camera_index} could not be opened.")

    if width > 0:
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    if height > 0:
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    if fps > 0:
        cap.set(cv2.CAP_PROP_FPS, fps)

    ok, frame = cap.read()
    if not ok or frame is None:
        cap.release()
        raise RuntimeError(f"Camera index {camera_index} opened, but no frame was received.")

    return cap


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


def draw_text_panel(
    frame: np.ndarray,
    lines: Iterable[str],
    origin: Tuple[int, int] = (16, 28),
    line_height: int = 24,
) -> None:
    lines = list(lines)
    if not lines:
        return

    x, y = origin
    width = max(260, max(len(line) for line in lines) * 10 + 24)
    height = line_height * len(lines) + 16
    overlay = frame.copy()
    cv2.rectangle(overlay, (x - 8, y - 24), (x - 8 + width, y - 24 + height), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.55, frame, 0.45, 0.0, frame)

    for idx, line in enumerate(lines):
        cv2.putText(
            frame,
            line,
            (x, y + idx * line_height),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.62,
            (255, 255, 255),
            2,
            cv2.LINE_AA,
        )


def resize_for_display(frame: np.ndarray, display_width: int) -> np.ndarray:
    if display_width <= 0 or frame.shape[1] <= display_width:
        return frame
    scale = display_width / float(frame.shape[1])
    display_height = int(frame.shape[0] * scale)
    return cv2.resize(frame, (display_width, display_height), interpolation=cv2.INTER_AREA)


def read_csv_rows(path: Path) -> List[Dict[str, str]]:
    import csv

    with path.open("r", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))
