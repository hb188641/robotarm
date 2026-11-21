"""WebSocket video/state (used over the internet so frames are not lumped)."""

import itertools
import json
import threading
import time
import urllib.error
import urllib.request

import pytest
import web_sim
from sim import arm
from sim.world import World
from sim.wsock import accept_key, frame
from test_share import CF, FakeTunnel
from websockets.exceptions import InvalidStatus
from websockets.sync.client import connect
from werkzeug.serving import make_server


@pytest.fixture(scope="module")
def world():
    w = World(arm.load_profile(), seed=4).start()
    yield w
    w.close()


@pytest.fixture(scope="module")
def tunnel():
    t = FakeTunnel()
    t.start()
    return t


@pytest.fixture(scope="module")
def server(world, tunnel):
    """A real HTTP server: WebSockets need the raw socket."""
    srv = make_server(
        "127.0.0.1", 0, web_sim.create_app(world, [], tunnel), threaded=True
    )
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"ws://127.0.0.1:{srv.server_port}", srv.server_port
    srv.shutdown()


def viewers(port):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/state") as r:
        return json.load(r)["viewers"]


def wait_for(fn, value, limit=3.0):
    end = time.monotonic() + limit
    while time.monotonic() < end and fn() != value:
        time.sleep(0.05)
    return fn()


def test_handshake_and_frame_encoding():
    # RFC 6455 section 1.3 example
    assert accept_key("dGhlIHNhbXBsZSBub25jZQ==") == "s3pPLMBiTxaQ9kYGzzhZRbK+xOo="
    assert frame(0x2, b"x" * 125)[:2] == b"\x82\x7d"
    assert frame(0x2, b"x" * 126)[:4] == b"\x82\x7e\x00\x7e"
    assert (
        frame(0x1, b"x" * 70000)[:2] == b"\x81\x7f"
        and len(frame(0x1, b"x" * 70000)) == 70010
    )


def test_frames_carry_their_render_time(server):
    url, port = server
    with connect(f"{url}/ws/wrist?fps=20&main=1", max_size=None) as ws:
        got = []
        for _ in range(4):
            msg = ws.recv(timeout=5)
            t, fid = web_sim.FRAME_HEADER.unpack_from(msg)
            got.append((t, fid))
            assert msg[web_sim.FRAME_HEADER.size :][:2] == b"\xff\xd8"  # a JPEG
        assert all(b[1] > a[1] and b[0] > a[0] for a, b in itertools.pairwise(got))
        assert abs(got[-1][0] - time.monotonic()) < 1.0  # same clock as the server
        assert wait_for(lambda: viewers(port), 1) == 1
    assert wait_for(lambda: viewers(port), 0) == 0  # closing the page frees it


def test_acked_stream_never_runs_ahead(server):
    """With ?ack=1 at most ACK_WINDOW frames are on the way unanswered, so a
    slow link skips frames instead of falling seconds behind."""
    url, _ = server
    with connect(f"{url}/ws/wrist?fps=20&ack=1", max_size=None) as ws:
        for _ in range(web_sim.ACK_WINDOW):
            ws.recv(timeout=5)
        with pytest.raises(TimeoutError):
            ws.recv(timeout=0.6)  # no answers yet: the server waits
        ws.send("1")
        ws.recv(timeout=5)  # one answer frees one frame


def test_state_is_pushed(server):
    url, _ = server
    with connect(f"{url}/ws/state") as ws:
        a = json.loads(ws.recv(timeout=5))
        b = json.loads(ws.recv(timeout=5))
    assert {"stage", "ticks", "cube", "viewers"} <= a.keys()
    assert b["time"] >= a["time"]


def test_unknown_stream_and_plain_requests_are_refused(server):
    url, port = server
    with pytest.raises(InvalidStatus) as err:
        connect(f"{url}/ws/nope")
    assert err.value.response.status_code == 404
    with pytest.raises(urllib.error.HTTPError) as plain:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/ws/wrist")
    assert plain.value.code == 400


def test_internet_visitors_need_the_key(server, tunnel):
    url, _ = server
    headers = dict(CF)  # what Cloudflare adds to requests from the internet
    with pytest.raises(InvalidStatus) as err:
        connect(f"{url}/ws/state", additional_headers=headers)
    assert err.value.response.status_code == 401
    cookie = {**headers, "Cookie": f"sim_key={tunnel.key}"}
    with connect(f"{url}/ws/state", additional_headers=cookie) as ws:
        assert "stage" in json.loads(ws.recv(timeout=5))
