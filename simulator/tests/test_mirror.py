"""Mirror sources and the offscreen snapshot, without hardware or a window."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import mirror
import pytest
from sim.sources import DemoSource, HttpSource

STATE = {f"motor_{i}": 2000 + i for i in range(1, 7)}


@pytest.fixture
def fake_server():
    """A stand-in for robot_arm_app: GET /api/state returns STATE."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path != "/api/state":
                self.send_error(404)
                return
            body = json.dumps(STATE).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def test_http_source_reads_api_state(fake_server):
    source = HttpSource(fake_server)
    source.poll_once()
    ticks, status = source.latest()
    assert ticks == STATE
    assert status.startswith("LIVE")


def test_http_source_keeps_last_pose_when_server_drops():
    calls = iter([dict(STATE), ConnectionRefusedError()])

    def fetch(_url):
        value = next(calls)
        if isinstance(value, Exception):
            raise value
        return value

    source = HttpSource("http://arm", fetch=fetch)
    source.poll_once()
    source.poll_once()
    ticks, status = source.latest()
    assert ticks == STATE
    assert status.startswith("OFFLINE")


def test_demo_source_eases_between_poses():
    now = [0.0]
    poses = {"a": {"motor_1": 1000}, "b": {"motor_1": 3000}}
    demo = DemoSource(poses, move_s=2.0, hold_s=1.0, clock=lambda: now[0])
    now[0] = 3.0  # second span starts: travel a → b
    start, _ = demo.latest()
    now[0] = 4.0  # halfway through the move
    middle, _ = demo.latest()
    now[0] = 5.5  # holding
    end, _ = demo.latest()
    assert (start["motor_1"], middle["motor_1"], end["motor_1"]) == (1000, 2000, 3000)
    assert end["motor_6"] == 2048  # missing motors default to center


def test_snapshot_renders_live_pose(fake_server, tmp_path):
    out = tmp_path / "frame.png"
    mirror.main(["--base-url", fake_server, "--snapshot", str(out)])
    assert out.stat().st_size > 10_000
