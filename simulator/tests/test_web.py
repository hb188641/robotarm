"""Browser panel API: the simulation thread behind Flask, without a browser."""

import time

import pytest
import web_sim
from sim import arm
from sim.world import World


@pytest.fixture(scope="module")
def client():
    world = World(arm.load_profile(), seed=5).start()
    world.call(world.set_speed, 4.0)
    app = web_sim.create_app(world)
    with app.test_client() as c:
        yield c
    world.close()


def wait_idle(client, limit_s=30.0):
    end = time.monotonic() + limit_s
    while time.monotonic() < end:
        state = client.get("/api/state").get_json()
        if not state["busy"]:
            return state
        time.sleep(0.05)
    raise AssertionError("task did not finish")


def test_page_and_assets_are_served(client):
    assert b"SO-101" in client.get("/").data
    assert client.get("/web/app.js").status_code == 200
    assert client.get("/web/style.css").status_code == 200


def test_still_frames_are_jpegs(client):
    for name in ("wrist", "overview"):
        r = client.get(f"/frame/{name}.jpg")
        assert r.status_code == 200 and r.data[:2] == b"\xff\xd8"
    assert client.get("/frame/nope.jpg").status_code == 404


def test_place_cube_validates_the_spot(client):
    r = client.post("/api/cube", json={"x": 0.23, "y": -0.05, "yaw_deg": 15})
    body = r.get_json()
    assert body["ok"] and body["reachable"]
    assert body["state"]["cube"]["x"] == pytest.approx(0.23, abs=1e-3)
    assert client.post("/api/cube", json={"x": 0.6, "y": 0}).status_code == 409
    assert client.post("/api/cube", json={"x": 0.02, "y": 0}).status_code == 409
    assert client.post("/api/cube", json={"y": 0}).status_code == 400


def test_pick_then_put_back_from_the_browser(client):
    client.post("/api/reset")
    client.post("/api/cube", json={"x": 0.21, "y": 0.06, "yaw_deg": -20})
    assert client.post("/api/pick").get_json()["ok"]
    # Busy: a second pick or moving the cube is refused with a message.
    busy = client.post("/api/pick")
    assert busy.status_code == 409 and busy.get_json()["error"]
    assert client.post("/api/cube", json={"x": 0.2, "y": 0}).status_code == 409

    state = wait_idle(client)
    assert state["result"] == "lifted" and state["holding"]
    # The referee (true cube height) agrees with the camera + gripper verdict.
    assert any("판정 맞음" in item["msg"] for item in state["log"])
    assert state["picks"]["misjudged"] == 0
    assert state["cube"]["z"] > 0.06
    assert state["sighting"] is not None

    assert client.post("/api/place").get_json()["ok"]
    state = wait_idle(client)
    assert not state["holding"]
    assert state["cube"]["z"] < 0.02
    assert client.post("/api/place").status_code == 409  # nothing held now


def test_stop_cancels_and_reset_restores(client):
    client.post("/api/reset")
    client.post("/api/pick")
    time.sleep(0.3)
    r = client.post("/api/stop").get_json()
    assert r["ok"] and not r["state"]["busy"]
    r = client.post("/api/reset").get_json()
    assert r["state"]["stage"] == "idle"
    assert r["state"]["ticks"]["motor_2"] == pytest.approx(1606, abs=3)


def test_auto_mode_and_speed(client):
    client.post("/api/reset")
    assert (
        client.post("/api/speed", json={"value": 9}).get_json()["state"]["speed"] == 4.0
    )
    assert client.post("/api/auto", json={"enabled": True}).get_json()["state"]["auto"]
    deadline = time.monotonic() + 40
    while time.monotonic() < deadline:
        if client.get("/api/state").get_json()["picks"]["total"] >= 1:
            break
        time.sleep(0.1)
    client.post("/api/stop")
    state = client.get("/api/state").get_json()
    assert state["picks"]["total"] >= 1 and not state["auto"]


def test_unknown_action(client):
    assert client.post("/api/fly").status_code == 404


def test_lan_urls_name_this_computer():
    urls = web_sim.lan_urls(8780)
    assert urls, "no network address found"
    for url in urls:
        assert url.startswith("http://") and url.endswith(":8780")
        assert "127.0.0.1" not in url and "localhost" not in url


def test_info_lists_share_urls_and_viewers_are_counted():
    world = World(arm.load_profile(), seed=1).start()
    try:
        app = web_sim.create_app(world, ["http://192.168.0.9:8780"])
        with app.test_client() as c:
            info = c.get("/api/info").get_json()
            assert info["share_urls"] == ["http://192.168.0.9:8780"]
            assert info["can_share"] and not info["remote"]
            assert info["internet"]["status"] == "off"
            assert c.get("/api/state").get_json()["viewers"] == 0
            thumb = c.get("/stream/overview.mjpg", buffered=False)
            next(thumb.response)  # thumbnails are not viewers
            assert c.get("/api/state").get_json()["viewers"] == 0
            stream = c.get("/stream/wrist.mjpg?main=1", buffered=False)
            chunk = next(stream.response)
            assert b"Content-Type: image/jpeg" in chunk
            assert c.get("/api/state").get_json()["viewers"] == 1
            stream.close()
            thumb.close()
            assert c.get("/api/state").get_json()["viewers"] == 0
    finally:
        world.close()


def test_auto_mode_keeps_going_with_new_cubes(client):
    """Regression: the auto cycle's own new cube was refused as "busy", which
    raised inside the simulation thread and froze the whole simulator."""
    client.post("/api/reset")
    client.post("/api/speed", json={"value": 4})
    spot = client.get("/api/state").get_json()["cube"]
    assert client.post("/api/auto", json={"enabled": True}).get_json()["ok"]
    deadline = time.monotonic() + 60
    state = {}
    while time.monotonic() < deadline:
        state = client.get("/api/state").get_json()
        if state["picks"]["total"] >= 2:
            break
        time.sleep(0.1)
    client.post("/api/stop")
    assert state["picks"]["total"] >= 2, state["log"]
    moved = client.get("/api/state").get_json()["cube"]
    assert (moved["x"], moved["y"]) != (spot["x"], spot["y"])  # a new cube appeared
    assert client.post("/api/pick").get_json()["ok"]  # still alive and responsive
    client.post("/api/stop")


def test_a_failing_task_does_not_kill_the_simulation():
    world = World(arm.load_profile(), seed=3).start()
    try:

        def broken():
            yield
            raise RuntimeError("boom")

        world.call(world._start_task, "broken", broken())
        time.sleep(0.3)
        assert world.thread.is_alive()
        state = world.state()
        assert (
            not state["busy"] and state["stage"] == "fail" and "boom" in state["status"]
        )
        assert world.call(world.random_cube)["reachable"] in (True, False)
    finally:
        world.close()
