from __future__ import annotations

import argparse
from pathlib import Path

from hand_common import (
    DEFAULT_DATASET_DIR,
    DEFAULT_MODEL_PATH,
    DEFAULT_SUMMARY_PATH,
    HAND_POSE_LABELS,
)
from tiny_hand_policy import HandPoseClassifier
from common.training import (
    LandmarkDataset,
    train_classifier,
    train_one_epoch as train_one_epoch,
    evaluate as _evaluate,
)

LANDMARK_COLUMNS = [f"{axis}{i}" for i in range(21) for axis in ("x", "y", "z")]


class HandPoseDataset(LandmarkDataset):
    def __init__(self, dataset_dir: Path) -> None:
        super().__init__(dataset_dir, HAND_POSE_LABELS, LANDMARK_COLUMNS)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="손 랜드마크 벡터로 펴짐/접힘 분류기를 학습."
    )
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET_DIR)
    parser.add_argument("--model-out", type=Path, default=DEFAULT_MODEL_PATH)
    parser.add_argument("--summary-out", type=Path, default=DEFAULT_SUMMARY_PATH)
    parser.add_argument("--epochs", type=int, default=20)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--val-ratio", type=float, default=0.2)
    parser.add_argument("--seed", type=int, default=42)
    return parser.parse_args()


def evaluate(model, loader, criterion, device):
    return _evaluate(model, loader, criterion, device, HAND_POSE_LABELS)


def main() -> None:
    args = parse_args()
    train_classifier(
        args,
        HandPoseDataset(args.dataset),
        HandPoseClassifier,
        HAND_POSE_LABELS,
        LANDMARK_COLUMNS,
    )


if __name__ == "__main__":
    main()
