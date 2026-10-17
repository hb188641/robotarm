from __future__ import annotations

import csv
import json
import time
from pathlib import Path
from typing import Dict, List


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def timestamp_string() -> str:
    return time.strftime("%Y%m%d_%H%M%S")


def write_json(path: Path, payload: Dict) -> None:
    ensure_dir(path.parent)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def read_csv_rows(path: Path) -> List[Dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_counts(labels_path: Path, labels) -> Dict[str, int]:
    counts = {label: 0 for label in labels}
    if not labels_path.exists():
        return counts

    with labels_path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            label = row.get("label")
            if label in counts:
                counts[label] += 1
    return counts


def append_row(
    labels_path: Path, label: str, vector, timestamp: float, columns
) -> None:
    exists = labels_path.exists()
    fieldnames = ["label", *columns, "timestamp"]
    row = {"label": label, "timestamp": f"{timestamp:.6f}"}
    row.update({col: f"{value:.6f}" for col, value in zip(columns, vector)})

    with labels_path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not exists:
            writer.writeheader()
        writer.writerow(row)
