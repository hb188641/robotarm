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

ARM_POSE_LABELS = ["extended", "folded"]
LABEL_DISPLAY_KO = {"extended": "펴짐", "folded": "접힘"}

LABEL_KEYS = {
    ord("o"): "extended",
    ord("f"): "folded",
}

RIGHT_SHOULDER_IDX = 12
RIGHT_ELBOW_IDX = 14
RIGHT_WRIST_IDX = 16
ARM_LANDMARK_INDICES = [RIGHT_SHOULDER_IDX, RIGHT_ELBOW_IDX, RIGHT_WRIST_IDX]

CONNECTIONS = mp.tasks.vision.PoseLandmarksConnections.POSE_LANDMARKS

# scripts/pose_common.py -> scripts/ -> arm_pose_lab/
LAB_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = LAB_DIR.parent.parent
DEFAULT_DATASET_DIR = LAB_DIR / "data" / "arm_pose"
DEFAULT_MODEL_PATH = LAB_DIR / "models" / "arm_pose_classifier.pt"
DEFAULT_SUMMARY_PATH = LAB_DIR / "models" / "arm_pose_training_summary.json"
POSE_LANDMARKER_MODEL_PATH = REPO_ROOT / "pose_landmarker_full.task"


def create_pose_landmarker(model_path: Path = POSE_LANDMARKER_MODEL_PATH):
    options = mp.tasks.vision.PoseLandmarkerOptions(
        base_options=mp.tasks.BaseOptions(model_asset_path=str(model_path)),
        running_mode=mp.tasks.vision.RunningMode.VIDEO,
        num_poses=1,
    )
    return mp.tasks.vision.PoseLandmarker.create_from_options(options)


def detect_pose(detector, frame_bgr: np.ndarray, timestamp_ms: int):
    """frame(BGR)에서 첫 번째 사람의 33개 pose landmark 리스트(.x/.y/.z)를 반환. 감지 실패 시 None."""
    rgb_frame = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
    mp_image = mp.Image(mp.ImageFormat.SRGB, rgb_frame)
    result = detector.detect_for_video(mp_image, timestamp_ms)
    if not result.pose_landmarks:
        return None
    return result.pose_landmarks[0]


def draw_pose(frame: np.ndarray, pose) -> None:
    height, width = frame.shape[:2]
    points = []

    for landmark in pose:
        x = int(landmark.x * width)
        y = int(landmark.y * height)
        points.append((x, y))

    for line in CONNECTIONS:
        cv2.line(frame, points[line.start], points[line.end], (0, 220, 255), 2)

    for idx in ARM_LANDMARK_INDICES:
        cv2.circle(frame, points[idx], 8, (0, 70, 255), -1)


def landmarks_to_vector(pose) -> np.ndarray:
    """
    오른쪽 어깨(12)/팔꿈치(14)/손목(16) 3개 landmark(x,y,z)를 어깨 기준 평행이동 +
    어깨~팔꿈치 거리로 스케일 정규화한 9차원 벡터로 변환.
    몸이 화면 어디에 있든, 카메라와의 거리가 달라져도 같은 팔 모양이면 같은 벡터가 나오도록 만든다.
    """
    points = np.array(
        [[pose[i].x, pose[i].y, pose[i].z] for i in ARM_LANDMARK_INDICES],
        dtype=np.float32,
    )  # (3, 3)

    origin = points[0]  # shoulder
    centered = points - origin

    scale = float(np.linalg.norm(centered[1]))  # shoulder -> elbow distance
    if scale < 1e-6:
        scale = 1e-6

    normalized = centered / scale
    return normalized.reshape(-1)  # (9,)
