"""Regression coverage for both standalone pose workflows, without hardware."""

import importlib
import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest
import requests
import torch

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(params=["hand", "arm"])
def workflow(request, monkeypatch):
    kind = request.param
    lab = ROOT / "TITI" / f"{kind}_pose_lab"
    monkeypatch.syspath_prepend(str(lab / "scripts"))
    return kind, lab


def test_dataset_collection_remains_readable_by_training(workflow, tmp_path):
    kind, _ = workflow
    collect = importlib.import_module(f"collect_{kind}_pose_dataset")
    train = importlib.import_module(f"train_{kind}_pose_classifier")
    label = "open" if kind == "hand" else "extended"
    size = 63 if kind == "hand" else 9
    path = tmp_path / "landmarks.csv"
    collect.append_row(path, label, np.arange(size), 123.5)
    collect.append_row(path, label, np.ones(size), 124.5)
    dataset = getattr(train, f"{kind.title()}PoseDataset")(tmp_path)
    assert len(dataset) == 2
    features, target = dataset[0]
    assert features.shape == (size,)
    assert features[0].item() == 0
    assert features[-1].item() == size - 1
    assert target.item() == 0
    assert collect.load_counts(path)[label] == 2


def test_existing_checkpoint_still_loads(workflow):
    kind, lab = workflow
    policy = importlib.import_module(f"tiny_{kind}_policy")
    model, checkpoint = policy.load_policy_checkpoint(
        lab / "models" / f"{kind}_pose_classifier.pt", torch.device("cpu")
    )
    size = 63 if kind == "hand" else 9
    with torch.no_grad():
        result = model(torch.zeros(1, size))
    assert result.shape == (1, 2)
    assert torch.isfinite(result).all()
    assert len(checkpoint["label_names"]) == 2


def test_importing_classifier_does_not_contact_robot(workflow, monkeypatch):
    kind, _ = workflow

    def unexpected_request(*args, **kwargs):
        pytest.fail("Importing a classifier must not enable motor torque")

    monkeypatch.setattr(requests, "post", unexpected_request)
    importlib.import_module(f"run_{kind}_pose_classifier")


def test_training_cli_saves_loadable_model_from_another_directory(workflow, tmp_path):
    kind, lab = workflow
    output = tmp_path / "model.pt"
    summary = tmp_path / "summary.json"
    result = subprocess.run(
        [
            sys.executable,
            str(lab / "scripts" / f"train_{kind}_pose_classifier.py"),
            "--epochs",
            "1",
            "--batch-size",
            "1024",
            "--model-out",
            str(output),
            "--summary-out",
            str(summary),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    policy = importlib.import_module(f"tiny_{kind}_policy")
    model, checkpoint = policy.load_policy_checkpoint(output, torch.device("cpu"))
    size = 63 if kind == "hand" else 9
    assert model(torch.zeros(1, size)).shape == (1, 2)
    report = json.loads(summary.read_text())
    assert len(report["history"]) == 1
    assert report["num_samples"] > 0
    assert report["best_val_acc"] == checkpoint["best_val_acc"]
