from __future__ import annotations

import argparse
import shutil
import time
from pathlib import Path
from typing import Dict

import cv2

from pose_common import (
    ARM_POSE_LABELS,
    DEFAULT_DATASET_DIR,
    LABEL_DISPLAY_KO,
    LABEL_KEYS,
    POSE_LANDMARKER_MODEL_PATH,
    create_pose_landmarker,
    detect_pose,
    draw_pose,
    draw_text_panel,
    ensure_dir,
    landmarks_to_vector,
    open_camera,
    resize_for_display,
    timestamp_string,
    write_json,
)

from common.data import load_counts as _load_counts, append_row as _append_row

LANDMARK_COLUMNS = [f"{axis}{i}" for i in range(3) for axis in ("x", "y", "z")]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="카메라로 오른팔(어깨/팔꿈치/손목) 랜드마크를 라벨링해서 펴짐/접힘 데이터셋을 수집."
    )
    parser.add_argument("--camera", type=int, default=0, help="카메라 인덱스.")
    parser.add_argument(
        "--dataset", type=Path, default=DEFAULT_DATASET_DIR, help="데이터셋 디렉터리."
    )
    parser.add_argument(
        "--model",
        type=Path,
        default=POSE_LANDMARKER_MODEL_PATH,
        help="pose_landmarker_full.task 경로.",
    )
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--display-width", type=int, default=1280)
    parser.add_argument(
        "--append", action="store_true", help="기존 데이터셋에 이어서 수집."
    )
    return parser.parse_args()


def load_counts(labels_path: Path) -> Dict[str, int]:
    return _load_counts(labels_path, ARM_POSE_LABELS)


def append_row(labels_path: Path, label: str, vector, timestamp: float) -> None:
    _append_row(labels_path, label, vector, timestamp, LANDMARK_COLUMNS)


def main() -> None:
    args = parse_args()

    cap = open_camera(args.camera, args.width, args.height, args.fps)
    if args.dataset.exists() and not args.append:
        shutil.rmtree(args.dataset)

    collection_mode = (
        "append existing dataset" if args.append else "new dataset (reset)"
    )
    dataset_dir = ensure_dir(args.dataset)
    labels_path = dataset_dir / "landmarks.csv"
    metadata_path = dataset_dir / "metadata.json"

    write_json(
        metadata_path,
        {
            "created_or_updated_at": timestamp_string(),
            "collection_mode": collection_mode,
            "task": "right arm extended/folded pose classification (shoulder-elbow-wrist)",
            "feature": "shoulder-centered, scale-normalized 3x3 landmark vector (9-dim)",
            "labels": ARM_POSE_LABELS,
        },
    )

    counts = load_counts(labels_path)
    window_name = "Collect arm pose dataset"
    last_label = "none"

    print("Controls: o=펴짐(extended)  f=접힘(folded)  q/ESC=종료")
    print(f"Dataset: {dataset_dir.resolve()}")
    print(f"Mode: {collection_mode}")

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
                if pose is not None:
                    draw_pose(display, pose)

                count_line = " ".join(
                    f"{label}:{counts[label]}" for label in ARM_POSE_LABELS
                )
                draw_text_panel(
                    display,
                    [
                        "Arm pose dataset collection (right arm)",
                        f"Mode: {collection_mode}",
                        "o = 펴짐(extended)   f = 접힘(folded)",
                        f"pose detected: {'yes' if pose is not None else 'no'}  last={last_label}",
                        count_line,
                    ],
                )

                cv2.imshow(window_name, resize_for_display(display, args.display_width))
                key = cv2.waitKey(1) & 0xFF

                if key in (ord("q"), 27):
                    break
                if key in LABEL_KEYS:
                    label = LABEL_KEYS[key]
                    if pose is None:
                        print("사람이 감지되지 않아 저장하지 않음.")
                        continue
                    vector = landmarks_to_vector(pose)
                    append_row(labels_path, label, vector, time.time())
                    counts[label] += 1
                    last_label = f"{label}({LABEL_DISPLAY_KO[label]})"
                    print(f"label={last_label} counts={counts}")
        finally:
            cap.release()
            cv2.destroyAllWindows()
            print(f"Saved landmarks: {labels_path.resolve()}")
            print(f"Final counts: {counts}")


if __name__ == "__main__":
    main()
