from __future__ import annotations

from pathlib import Path
import sys
from typing import Dict, Tuple

import torch
from torch import nn

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from common.device import select_device as select_device


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


def load_policy_checkpoint(
    path: Path, device: torch.device
) -> Tuple[ArmPoseClassifier, Dict]:
    checkpoint = torch.load(path, map_location=device)
    labels = checkpoint["label_names"]
    model = ArmPoseClassifier(
        input_dim=checkpoint.get("input_dim", 9), num_classes=len(labels)
    )
    model.load_state_dict(checkpoint["model_state"])
    model.to(device)
    model.eval()
    return model, checkpoint
