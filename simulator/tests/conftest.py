import sys
from pathlib import Path

SIM = Path(__file__).resolve().parents[1]
for path in (SIM, SIM.parent):  # `sim` package and the repo root (TITI.*)
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
