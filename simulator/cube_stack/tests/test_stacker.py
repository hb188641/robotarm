import ast
from pathlib import Path

import pytest
import stack_sim
from stack import referee, scene

STACK = Path(__file__).resolve().parents[1] / "stack"


def run(argv):
    args = stack_sim.parse_args(["--headless", "--quiet", *argv])
    args.once = True
    ep = stack_sim.Episode(args, log=lambda _m: None)
    for _ in ep.cycle():
        ep.sim.step(1 / stack_sim.FPS)
    return ep


@pytest.mark.parametrize("seed,order", [(0, "red,yellow,blue"), (4, "blue,red,yellow")])
def test_stacks_and_knows_it(seed, order):
    ep = run(["--seed", str(seed), "--order", order])
    ep.close()
    g = ep.grades[-1]
    assert g["stacked"], stack_sim.summary(g)
    assert g["claim"] == "stacked"
    assert [L["color"] for L in g["layers"]] == order.split(",")
    assert g["seconds"] < 60


def test_notices_a_knocked_over_tower():
    ep = run(["--seed", "2"])
    m, d = ep.m, ep.d
    scene.place_cube(m, d, "blue", 0.12, -0.20)  # someone takes the top cube away
    st = ep.stacker
    for _ in st.final_check():
        ep.sim.step(1 / stack_sim.FPS)
    assert not referee.grade(m, d, ep.order)["stacked"]
    assert st.result == "failed"
    ep.close()


FORBIDDEN = {
    "cube_pose",
    "place_cube",
    "place_layout",
    "referee",
    "qpos",
    "xpos",
    "xmat",
}


@pytest.mark.parametrize("name", ["stacker.py", "eye.py", "colors.py"])
def test_decisions_never_read_ground_truth(name):
    tree = ast.parse((STACK / name).read_text())
    used = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    used |= {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    used |= {
        a.name.split(".")[-1]
        for n in ast.walk(tree)
        if isinstance(n, (ast.Import, ast.ImportFrom))
        for a in n.names
    }
    assert not used & FORBIDDEN
