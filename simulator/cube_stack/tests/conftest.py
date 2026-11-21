import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import mujoco
import pytest
import stack.paths  # noqa: F401  (simulator/ and the repo root)
from sim import arm
from sim.physics_arm import SimArm
from stack import scene


@pytest.fixture(scope="session")
def model():
    return scene.build_model(arm.load_profile())


@pytest.fixture
def world(model):
    d = mujoco.MjData(model)
    return model, d, SimArm(model, d)
