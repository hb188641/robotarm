"""MuJoCo simulator for the SO-101 robot arm project.

The simulator reuses the project's own code (TITI/voice_motor kinematics and
vision), so the repository root must be importable wherever this runs from.
"""

import sys
from pathlib import Path

_REPO = str(Path(__file__).resolve().parents[2])
if _REPO not in sys.path:
    sys.path.append(_REPO)
