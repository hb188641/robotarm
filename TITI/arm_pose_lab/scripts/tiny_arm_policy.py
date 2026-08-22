from __future__ import annotations

from pathlib import Path
from typing import Dict, Tuple

import torch
from torch import nn


class ArmPoseClassifier(nn.Module):
    def __init__(self, input_dim: int = 9, num_classes: int = 2) -> None:
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(input_dim, 32),
            nn.ReLU(inplace=True),
            nn.Linear(32, 16),
            nn.ReLU(inplace=True),
            nn.Linear(16, num_classes),
        )

    def forward(self, features: torch.Tensor) -> torch.Tensor:
        return self.net(features)


def select_device() -> torch.device:
    if torch.backends.mps.is_available():
        return torch.device("mps")
    if torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")


def load_policy_checkpoint(path: Path, device: torch.device) -> Tuple[ArmPoseClassifier, Dict]:
    checkpoint = torch.load(path, map_location=device)
    labels = checkpoint["label_names"]
    model = ArmPoseClassifier(input_dim=checkpoint.get("input_dim", 9), num_classes=len(labels))
    model.load_state_dict(checkpoint["model_state"])
    model.to(device)
    model.eval()
    return model, checkpoint
