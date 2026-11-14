"""Internet sharing: the access-key gate and the cloudflared tunnel wrapper."""

import stat
import time

import pytest
import web_sim
from sim import arm
from sim.share import COOKIE, Tunnel, key_matches, new_key, via_tunnel
from sim.world import World

TUNNEL_HOST = "lucky-words-here.trycloudflare.com"
CF = {"Cf-Connecting-Ip": "203.0.113.7", "Cf-Ray": "abc123-ICN"}


class FakeTunnel(Tunnel):
    """A tunnel that is "on" without starting cloudflared."""

    def __init__(self):
        super().__init__(8780, binary="/bin/true")
        self.started = self.stopped = 0

    def start(self):
        self.started += 1
        self.key, self.url, self.status = (
            "k3y-for-tests",
            f"https://{TUNNEL_HOST}",
            "on",
        )

    def stop(self):
        self.stopped += 1
        self.key, self.url, self.status = None, None, "off"


@pytest.fixture(scope="module")
def world():
    w = World(arm.load_profile(), seed=2).start()
    yield w
    w.close()


@pytest.fixture
def tunnel():
    t = FakeTunnel()
    t.start()
    return t


@pytest.fixture
def app(world, tunnel):
    return web_sim.create_app(world, [], tunnel)


def remote(client, method, path, **kw):
    headers = {**CF, **kw.pop("headers", {})}
    return client.open(
        path, method=method, base_url=f"https://{TUNNEL_HOST}", headers=headers, **kw
    )


def test_key_helpers():
    a, b = new_key(), new_key()
    assert a != b and len(a) >= 12
    assert key_matches(a, a) and not key_matches(a, b)
    assert not key_matches(None, a) and not key_matches(a, None)
    assert via_tunnel(CF, "localhost:8780")
    assert via_tunnel({}, TUNNEL_HOST)
    assert not via_tunnel({}, "localhost:8780")
    assert not via_tunnel({}, "192.168.0.205:8780")


def test_internet_visitor_without_key_is_stopped(app):
    with app.test_client() as c:
        page = remote(c, "GET", "/")
        assert page.status_code == 401 and "접속 키".encode() in page.data
        assert remote(c, "GET", "/api/state").status_code == 401
        assert remote(c, "POST", "/api/pick").status_code == 401
        assert remote(c, "GET", "/frame/wrist.jpg").status_code == 401
        wrong = remote(c, "GET", "/?key=nope")
        assert wrong.status_code == 401 and "맞지 않습니다".encode() in wrong.data


def test_link_with_key_sets_a_cookie_and_hides_the_key(app, tunnel):
    with app.test_client() as c:
        r = remote(c, "GET", f"/?key={tunnel.key}")
        assert r.status_code == 302 and r.headers["Location"] == "/"
        cookie = r.headers["Set-Cookie"]
        assert (
            f"{COOKIE}={tunnel.key}" in cookie
            and "HttpOnly" in cookie
            and "Secure" in cookie
        )
        # The cookie now opens everything.
        assert remote(c, "GET", "/").status_code == 200
        assert remote(c, "GET", "/api/state").status_code == 200
        info = remote(c, "GET", "/api/info").get_json()
        assert info["remote"] and not info["can_share"]


def test_turning_sharing_off_revokes_the_key(app, tunnel):
    with app.test_client() as c:
        key = tunnel.key
        remote(c, "GET", f"/?key={key}")
        assert remote(c, "GET", "/api/state").status_code == 200
        tunnel.stop()
        assert remote(c, "GET", "/api/state").status_code == 401
        tunnel.start()
        tunnel.key = "a-brand-new-key"
        assert remote(c, "GET", "/api/state").status_code == 401  # old cookie


def test_only_this_computer_switches_sharing(app, tunnel):
    with app.test_client() as c:
        remote(c, "GET", f"/?key={tunnel.key}")
        assert (
            remote(c, "POST", "/api/share", json={"enabled": False}).status_code == 403
        )
        lan = c.post(
            "/api/share",
            json={"enabled": False},
            environ_base={"REMOTE_ADDR": "192.168.0.9"},
        )
        assert lan.status_code == 403
        assert tunnel.stopped == 0
        local = c.post("/api/share", json={"enabled": False})  # 127.0.0.1
        assert (
            local.status_code == 200 and local.get_json()["internet"]["status"] == "off"
        )
        assert tunnel.stopped == 1
        info = c.get("/api/info").get_json()
        assert info["can_share"] and not info["remote"]


def test_local_and_lan_visitors_need_no_key(app):
    with app.test_client() as c:
        assert c.get("/api/state").status_code == 200
        lan = c.get("/api/state", base_url="http://192.168.0.205:8780")
        assert lan.status_code == 200


def test_stream_frame_rate_is_capped(app):
    with app.test_client() as c:
        r = c.get("/stream/wrist.mjpg?fps=4", buffered=False)
        frames = r.response
        next(frames)
        begin = time.monotonic()
        for _ in range(3):
            next(frames)
        elapsed = time.monotonic() - begin
        r.close()
    assert elapsed > 3 / 4 * 0.8  # ~0.75 s for 3 frames at 4 fps


def fake_cloudflared(tmp_path, lines, linger=True):
    script = tmp_path / "cloudflared"
    body = "\n".join(f"echo '{line}' >&2" for line in lines)
    script.write_text(f"#!/bin/sh\n{body}\n" + ("sleep 30\n" if linger else "exit 1\n"))
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return str(script)


def wait_status(t, status, limit=5.0):
    end = time.monotonic() + limit
    while time.monotonic() < end and t.status != status:
        time.sleep(0.05)
    return t.status


def test_tunnel_reads_the_public_url(tmp_path):
    binary = fake_cloudflared(
        tmp_path,
        [
            "INF Requesting new quick Tunnel on trycloudflare.com...",
            "INF |  https://brave-otter-sample.trycloudflare.com  |",
        ],
    )
    t = Tunnel(8780, binary=binary)
    t.start()
    try:
        assert wait_status(t, "on") == "on"
        assert t.url == "https://brave-otter-sample.trycloudflare.com"
        assert t.link() == f"{t.url}/?key={t.key}"
    finally:
        t.stop()
    assert t.status == "off" and t.link() is None and t.key is None


def test_tunnel_reports_a_crash(tmp_path):
    t = Tunnel(
        8780, binary=fake_cloudflared(tmp_path, ["ERR failed to connect"], linger=False)
    )
    t.start()
    assert wait_status(t, "error") == "error"
    assert "failed to connect" in t.error


def test_missing_cloudflared_is_explained(tmp_path):
    t = Tunnel(8780, binary=None)
    t.binary = None
    t.start()
    assert t.status == "error" and "brew install cloudflared" in t.error
