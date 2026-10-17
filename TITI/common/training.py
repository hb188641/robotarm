from __future__ import annotations

import json
import random
from collections import Counter
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import torch
from torch import nn
from torch.utils.data import DataLoader, Dataset, random_split
from tqdm import tqdm

from .data import ensure_dir, read_csv_rows
from .device import select_device


class LandmarkDataset(Dataset):
    def __init__(self, dataset_dir: Path, labels, columns) -> None:
        self.labels = labels
        self.columns = columns
        self.rows = self._load_rows(dataset_dir / "landmarks.csv")
        self.label_to_index = {label: idx for idx, label in enumerate(self.labels)}

    def _load_rows(self, labels_path: Path) -> List[Dict[str, str]]:
        if not labels_path.exists():
            raise FileNotFoundError(f"landmarks.csv not found: {labels_path}")
        rows = read_csv_rows(labels_path)
        valid_rows = [row for row in rows if row.get("label") in self.labels]
        if not valid_rows:
            raise RuntimeError(
                "No valid samples found. Collect data first with the corresponding dataset collector."
            )
        return valid_rows

    def __len__(self) -> int:
        return len(self.rows)

    def __getitem__(self, index: int) -> Tuple[torch.Tensor, torch.Tensor]:
        row = self.rows[index]
        vector = np.array([float(row[col]) for col in self.columns], dtype=np.float32)
        features = torch.from_numpy(vector)
        label = torch.tensor(self.label_to_index[row["label"]], dtype=torch.long)
        return features, label

    def label_counts(self) -> Counter:
        return Counter(row["label"] for row in self.rows)


def train_one_epoch(
    model: nn.Module,
    loader: DataLoader,
    optimizer: torch.optim.Optimizer,
    criterion: nn.Module,
    device: torch.device,
) -> Tuple[float, float]:
    model.train()
    total_loss = 0.0
    correct = 0
    total = 0
    for features, labels in tqdm(loader, desc="train", leave=False):
        features = features.to(device)
        labels = labels.to(device)

        optimizer.zero_grad(set_to_none=True)
        logits = model(features)
        loss = criterion(logits, labels)
        loss.backward()
        optimizer.step()

        total_loss += float(loss.item()) * labels.size(0)
        correct += int((logits.argmax(dim=1) == labels).sum().item())
        total += labels.size(0)
    return total_loss / max(1, total), correct / max(1, total)


@torch.no_grad()
def evaluate(
    model: nn.Module,
    loader: DataLoader,
    criterion: nn.Module,
    device: torch.device,
    label_names,
) -> Tuple[float, float, List[List[int]]]:
    model.eval()
    total_loss = 0.0
    correct = 0
    total = 0
    matrix = [[0 for _ in label_names] for _ in label_names]
    for features, labels in tqdm(loader, desc="val", leave=False):
        features = features.to(device)
        labels = labels.to(device)

        logits = model(features)
        loss = criterion(logits, labels)
        preds = logits.argmax(dim=1)

        total_loss += float(loss.item()) * labels.size(0)
        correct += int((preds == labels).sum().item())
        total += labels.size(0)
        for target, pred in zip(labels.cpu().tolist(), preds.cpu().tolist()):
            matrix[target][pred] += 1
    return total_loss / max(1, total), correct / max(1, total), matrix


def train_classifier(args, dataset, model_factory, label_names, columns) -> None:
    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)

    counts = dataset.label_counts()
    print(f"Samples: {len(dataset)}")
    print("Label counts:", dict(counts))
    for label in label_names:
        if counts[label] < 10:
            print(
                f"Warning: label '{label}' has only {counts[label]} samples. Add more data for stable behavior."
            )

    val_size = max(1, int(len(dataset) * args.val_ratio))
    train_size = max(1, len(dataset) - val_size)
    if train_size + val_size > len(dataset):
        val_size = len(dataset) - train_size

    generator = torch.Generator().manual_seed(args.seed)
    train_dataset, val_dataset = random_split(
        dataset, [train_size, val_size], generator=generator
    )
    train_loader = DataLoader(
        train_dataset, batch_size=args.batch_size, shuffle=True, num_workers=0
    )
    val_loader = DataLoader(
        val_dataset, batch_size=args.batch_size, shuffle=False, num_workers=0
    )

    device = select_device()
    print(f"Device: {device}")
    model = model_factory(input_dim=len(columns), num_classes=len(label_names)).to(
        device
    )
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=1e-4)
    criterion = nn.CrossEntropyLoss()

    history = []
    best_val_acc = -1.0
    best_state = None
    best_matrix = None

    for epoch in range(1, args.epochs + 1):
        train_loss, train_acc = train_one_epoch(
            model, train_loader, optimizer, criterion, device
        )
        val_loss, val_acc, matrix = evaluate(
            model, val_loader, criterion, device, label_names
        )
        history.append(
            {
                "epoch": epoch,
                "train_loss": train_loss,
                "train_acc": train_acc,
                "val_loss": val_loss,
                "val_acc": val_acc,
            }
        )
        print(
            f"epoch {epoch:02d} | train loss {train_loss:.4f} acc {train_acc:.3f} | val loss {val_loss:.4f} acc {val_acc:.3f}"
        )

        if val_acc > best_val_acc:
            best_val_acc = val_acc
            best_state = {
                key: value.detach().cpu() for key, value in model.state_dict().items()
            }
            best_matrix = matrix

    ensure_dir(args.model_out.parent)
    checkpoint = {
        "model_state": best_state if best_state is not None else model.state_dict(),
        "label_names": label_names,
        "input_dim": len(columns),
        "class_counts": dict(counts),
        "best_val_acc": best_val_acc,
    }
    torch.save(checkpoint, args.model_out)
    print(f"Saved model: {args.model_out.resolve()}")

    summary = {
        "dataset": str(args.dataset),
        "model_out": str(args.model_out),
        "num_samples": len(dataset),
        "class_counts": dict(counts),
        "history": history,
        "best_val_acc": best_val_acc,
        "confusion_matrix_labels": label_names,
        "confusion_matrix": best_matrix,
    }
    ensure_dir(args.summary_out.parent)
    args.summary_out.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"Saved summary: {args.summary_out.resolve()}")
