"""Put `simulator/` (the `sim` package) and the repo root (`TITI.*`) on sys.path."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]  # simulator/cube_stack
SIM = HERE.parent  # simulator
REPO = SIM.parent
for _p in (SIM, REPO):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
