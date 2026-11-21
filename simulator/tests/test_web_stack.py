"""The stack panel and the home router, on one app (no browser)."""

import time

import pytest
import web_sim
from sim import arm
from sim.world import World


@pytest.fixture(scope="module")
def sims():
    from stack.world import StackWorld

    profile = arm.load_profile()
    made = {
        "pick": web_sim.Sim(
            "pick", "큐브 집기", lambda: World(profile, seed=5).start()
        ),
        "stack": web_sim.Sim(
            "stack", "큐브 쌓기", lambda: StackWorld(profile, seed=3).start()
        ),
    }
    yield made
    for s in made.values():
        s.close()


@pytest.fixture(scope="module")
def client(sims):
    with web_sim.create_app(sims).test_client() as c:
        yield c


def wait_idle(client, limit_s=90.0):
    end = time.monotonic() + limit_s
    while time.monotonic() < end:
        state = client.get("/stack/api/state").get_json()
        if not state["busy"]:
            return state
        time.sleep(0.1)
    raise AssertionError("task did not finish")


def test_simulations_start_only_when_opened(client, sims):
    listed = {s["name"]: s for s in client.get("/api/sims").get_json()}
    assert set(listed) == {"pick", "stack"}
    assert not sims["pick"].running
    assert b'data-base="/stack"' in client.get("/stack/").data
    state = client.get("/stack/api/state").get_json()
    assert set(state["cubes"]) == {"red", "yellow", "blue"}
    assert sims["stack"].running and not sims["pick"].running  # pick still asleep


def test_stack_streams_are_jpegs(client):
    for name in ("overview", "top", "wrist", "top_seen", "wrist_seen"):
        r = client.get(f"/stack/frame/{name}.jpg")
        assert r.status_code == 200 and r.data[:2] == b"\xff\xd8", name
    assert client.get("/stack/frame/detector.jpg").status_code == 404


def test_moving_cubes_and_order_are_validated(client):
    state = client.get("/stack/api/state").get_json()
    red = state["cubes"]["red"]
    assert client.post("/stack/api/cube", json={"x": 0.2, "y": 0}).status_code == 400
    too_close = {"color": "yellow", "x": red["x"] + 0.01, "y": red["y"], "yaw_deg": 0}
    assert client.post("/stack/api/cube", json=too_close).status_code == 409
    off = {"color": "blue", "x": 0.6, "y": 0.0}
    assert client.post("/stack/api/cube", json=off).status_code == 409
    assert (
        client.post(
            "/stack/api/order", json={"order": ["red", "red", "blue"]}
        ).status_code
        == 409
    )
    assert client.post("/stack/api/order", json={"order": "red"}).status_code == 400
    r = client.post(
        "/stack/api/order", json={"order": ["blue", "red", "yellow"]}
    ).get_json()
    assert r["ok"] and r["state"]["order"] == ["blue", "red", "yellow"]
    assert client.post("/stack/api/fly").status_code == 404


def test_stack_from_the_browser_and_grade(client):
    client.post("/stack/api/reset")
    client.post("/stack/api/speed", json={"value": 4})
    client.post("/stack/api/order", json={"order": ["red", "yellow", "blue"]})
    assert client.post("/stack/api/start").get_json()["ok"]
    assert client.post("/stack/api/start").status_code == 409  # already busy
    state = wait_idle(client)
    g = state["grade"]
    assert g is not None and g["stacked"] and g["claim"] == "stacked", state["log"][-3:]
    assert state["stacks"] == {"ok": 1, "total": 1, "misjudged": 0}
    # a new layout scatters the tower again
    assert client.post("/stack/api/cube/random").get_json()["ok"]
    cubes = client.get("/stack/api/state").get_json()["cubes"]
    assert all(abs(c["z"] - state["cube_size"] / 2) < 0.002 for c in cubes.values())


def test_stop_cancels_a_stack(client):
    client.post("/stack/api/reset")
    client.post("/stack/api/start")
    time.sleep(0.5)
    r = client.post("/stack/api/stop").get_json()
    assert r["ok"] and not r["state"]["busy"] and r["state"]["stage"] == "idle"
