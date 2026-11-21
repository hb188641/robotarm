"""Browser control panel for the first-person cube pick simulation.

    python simulator/web_sim.py            # then open http://localhost
    python simulator/web_sim.py --open     # also opens the browser
    python simulator/web_sim.py --lan      # other computers on the same network too
    python simulator/web_sim.py --share    # anywhere on the internet (Cloudflare tunnel)
    (or double-click simulator/시뮬레이터 열기.command in Finder: --lan --open;
     internet sharing can then be switched on from the page)

The simulation runs here (no `mjpython` needed: nothing opens a MuJoCo
window); the browser shows its camera streams and sends button / map clicks.
Requests arriving through the internet tunnel need the access key.
"""

from __future__ import annotations

import argparse
import atexit
import contextlib
import json
import socket
import struct
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

from flask import Flask, Response, jsonify, redirect, request, send_from_directory

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sim import arm
from sim.share import COOKIE, Tunnel, key_matches, via_tunnel
from sim.world import STREAMS, CommandError, World
from sim.wsock import Closed, WebSocket

WEB = Path(__file__).resolve().parent / "web"
DEFAULT_PORT = 80  # plain http://<address>, no port to type
FALLBACK_PORT = 8780  # when port 80 is taken or not allowed
MAX_FPS = 20
STATE_HZ = 12
KEY_COOKIE_AGE = 12 * 3600
# Each WebSocket video message: render time (s, server clock), frame id, JPEG.
FRAME_HEADER = struct.Struct("<dI")
# With ?ack=1 the page answers every frame; at most this many frames may be on
# the way unanswered. Otherwise a slow link (the internet tunnel) piles frames
# up in socket buffers and the picture falls seconds behind: now frames are
# skipped instead, so the delay stays around one round trip.
ACK_WINDOW = 2
ACK_STALL = 2.0  # s without any answer: assume lost, start sending again


class Upgraded(Response):
    """Returned after a WebSocket ends: the socket was used directly, so
    Werkzeug must not write an HTTP response (it treats this as a dropped
    connection and stays quiet)."""

    def __call__(self, environ, start_response):
        raise ConnectionError("websocket finished")


def fps_arg(default: float = MAX_FPS) -> float:
    try:
        return min(max(float(request.args.get("fps", default)), 1.0), MAX_FPS)
    except ValueError:
        return default


def http_url(host: str, port: int) -> str:
    return f"http://{host}" if port == 80 else f"http://{host}:{port}"


def port_free(host: str, port: int) -> bool:
    """Can this server listen on host:port? (taken, or not allowed below 1024)"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((host, port))
        return True
    except OSError:
        return False


def lan_urls(port: int) -> list[str]:
    """Addresses other devices on this network can use to reach this computer.

    The primary IPv4 comes from a UDP socket "connected" toward a public
    address: no packet is sent, the OS just picks the outgoing interface.
    """
    urls = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))  # TEST-NET-1, never actually contacted
            ip = s.getsockname()[0]
        if not ip.startswith("127."):
            urls.append(http_url(ip, port))
    except OSError:
        pass
    name = None
    if sys.platform == "darwin":  # Bonjour name, e.g. my-mac.local
        try:
            name = subprocess.run(
                ["scutil", "--get", "LocalHostName"],
                check=False,
                capture_output=True,
                text=True,
                timeout=2,
            ).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            name = None
    if name:
        urls.append(http_url(f"{name}.local", port))
    return urls


KEY_PAGE = """<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>접속 키 필요</title>
<style>
  :root {{ --bg:#f4f2ee; --card:#fff; --ink:#1d1d1f; --muted:#6b6a66; --line:#e3e0da; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg:#141414; --card:#1e1e1f; --ink:#ececec; --muted:#9b9a96; --line:#2f2f31; }}
  }}
  body {{ margin:0; min-height:100vh; display:grid; place-items:center; background:var(--bg);
         color:var(--ink); font:15px/1.5 -apple-system, "Apple SD Gothic Neo", sans-serif; padding:16px; }}
  form {{ background:var(--card); border:1px solid var(--line); border-radius:14px; padding:24px;
          width:min(360px, 100%); box-sizing:border-box; }}
  h1 {{ font-size:18px; margin:0 0 6px; }} p {{ color:var(--muted); margin:0 0 16px; font-size:14px; }}
  input {{ width:100%; box-sizing:border-box; font:16px ui-monospace, Menlo, monospace; padding:10px 12px;
           border:1px solid var(--line); border-radius:10px; background:var(--bg); color:var(--ink); }}
  button {{ margin-top:12px; width:100%; padding:10px; border:0; border-radius:10px; font:inherit;
            font-weight:600; background:#2563eb; color:#fff; cursor:pointer; }}
  .err {{ color:#dc2626; font-size:13px; margin-top:10px; }}
</style></head>
<body><form method="get" action="/">
  <h1>SO-101 시뮬레이터</h1>
  <p>공유받은 링크로 들어오거나, 받은 접속 키를 입력하세요.</p>
  <input name="key" placeholder="접속 키" autocomplete="off" autofocus>
  <button type="submit">들어가기</button>
  {error}
</form></body></html>"""


def create_app(
    world: World, share_urls: list[str] | None = None, tunnel: Tunnel | None = None
) -> Flask:
    app = Flask(__name__, static_folder=None)
    viewers = {"n": 0}
    viewers_lock = threading.Lock()
    tunnel = tunnel or Tunnel(DEFAULT_PORT)

    def from_internet() -> bool:
        return via_tunnel(request.headers, request.host)

    def from_this_computer() -> bool:
        return request.remote_addr in ("127.0.0.1", "::1") and not from_internet()

    @app.before_request
    def require_key():
        """Internet visitors need the key: ?key= once, then a cookie."""
        if not from_internet():
            return None
        key = tunnel.key if tunnel.status == "on" else None
        given = request.args.get("key")
        if key_matches(given, key):
            if request.method == "GET" and request.path == "/":
                # Drop the key from the address bar; remember it in a cookie.
                resp = redirect("/?still=1" if "still" in request.args else "/")
                resp.set_cookie(
                    COOKIE,
                    key,
                    max_age=KEY_COOKIE_AGE,
                    httponly=True,
                    secure=True,
                    samesite="Lax",
                )
                return resp
            return None
        if key_matches(request.cookies.get(COOKIE), key):
            return None
        if given:
            time.sleep(0.5)  # slow down guessing
        if request.method == "GET" and request.path == "/":
            error = '<div class="err">접속 키가 맞지 않습니다.</div>' if given else ""
            return Response(
                KEY_PAGE.format(error=error), status=401, mimetype="text/html"
            )
        return jsonify({"ok": False, "error": "접속 키가 필요합니다."}), 401

    def command(fn, *args):
        try:
            result = world.call(fn, *args)
        except CommandError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 409
        return jsonify({"ok": True, **(result or {}), "state": world.state()})

    @app.get("/")
    def index():
        return send_from_directory(WEB, "index.html")

    @app.get("/web/<path:name>")
    def static_file(name):
        return send_from_directory(WEB, name)

    @contextlib.contextmanager
    def watching(counted: bool):
        """One big view per open page = one viewer."""
        if counted:
            with viewers_lock:
                viewers["n"] += 1
        try:
            yield
        finally:  # the browser closed the page or switched views
            if counted:
                with viewers_lock:
                    viewers["n"] -= 1

    @app.get("/api/state")
    def state():
        return jsonify({**world.state(), "viewers": viewers["n"]})

    @app.get("/api/info")
    def info():
        """How other devices can open this page, and who may change sharing."""
        return jsonify(
            {
                "share_urls": share_urls or [],
                "internet": tunnel.info(),
                "can_share": from_this_computer(),
                "remote": from_internet(),
            }
        )

    @app.post("/api/share")
    def share():
        """Internet sharing on/off: only from this computer's own browser."""
        if not from_this_computer():
            return jsonify(
                {
                    "ok": False,
                    "error": "인터넷 공유는 시뮬레이터를 켠 컴퓨터에서만 바꿀 수 있습니다.",
                }
            ), 403
        enabled = bool((request.get_json(silent=True) or {}).get("enabled"))
        if enabled:
            tunnel.start()
        else:
            tunnel.stop()
        return jsonify({"ok": tunnel.status != "error", "internet": tunnel.info()})

    @app.get("/stream/<name>.mjpg")
    def stream(name):
        if name not in STREAMS:
            return jsonify({"error": f"unknown stream {name}"}), 404
        fps = fps_arg()
        main = request.args.get("main") == "1"

        def frames():
            with watching(main):
                last, sent = 0, 0.0
                while world.thread.is_alive():
                    # Wait out the frame interval: the next frame() call then
                    # returns the newest picture, skipping the ones between.
                    time.sleep(max(0.0, 1 / fps - (time.monotonic() - sent)))
                    last, jpg = world.frame(name, last)
                    if not jpg:
                        continue
                    sent = time.monotonic()
                    yield (
                        b"--frame\r\nContent-Type: image/jpeg\r\n"
                        + f"Content-Length: {len(jpg)}\r\n\r\n".encode()
                        + jpg
                        + b"\r\n"
                    )

        return Response(
            frames(),
            mimetype="multipart/x-mixed-replace; boundary=frame",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    @app.get("/ws/<name>", websocket=True)  # Werkzeug routes upgrades separately
    def ws_stream(name):
        """Camera frames (or, for "state", the panel state) over a WebSocket.

        Used over the internet: the tunnel passes WebSocket messages through
        one at a time, where a long MJPEG response arrives in lumps. Each frame
        carries its render time so the page can play them back evenly.
        """
        if name not in (*STREAMS, "state"):
            return jsonify({"error": f"unknown stream {name}"}), 404
        ws = WebSocket.accept(request.environ)
        if ws is None:
            return jsonify({"ok": False, "error": "WebSocket 연결이 필요합니다."}), 400
        try:
            if name == "state":
                push_state(ws)
            else:
                push_frames(
                    ws,
                    name,
                    fps_arg(),
                    request.args.get("main") == "1",
                    ACK_WINDOW if request.args.get("ack") == "1" else 0,
                )
        except Closed:
            pass
        finally:
            ws.finish()
        return Upgraded()

    def push_state(ws: WebSocket) -> None:
        last = None
        while world.thread.is_alive():
            ws.receive(timeout=1 / STATE_HZ)  # also notices a closed page
            body = json.dumps({**world.state(), "viewers": viewers["n"]})
            if body != last:
                ws.send(body)
                last = body

    def push_frames(
        ws: WebSocket, name: str, fps: float, main: bool, window: int = 0
    ) -> None:
        with watching(main):
            last, sent, unacked, heard = 0, 0.0, 0, time.monotonic()
            while world.thread.is_alive():
                now = time.monotonic()
                if window and unacked >= window and now - heard > ACK_STALL:
                    unacked = 0
                blocked = window and unacked >= window
                wait = 0.1 if blocked else max(0.0, 1 / fps - (now - sent))
                if ws.receive(timeout=wait) is not None:  # an ack (any message)
                    unacked, heard = max(0, unacked - 1), time.monotonic()
                    continue
                if blocked:
                    continue
                fid, rendered, jpg = world.frame_at(name, last)
                if not jpg or fid == last:
                    continue
                last, sent = fid, time.monotonic()
                ws.send(FRAME_HEADER.pack(rendered, fid) + jpg)
                if not unacked:
                    heard = sent  # the stall clock starts with the first unanswered frame
                unacked += 1

    @app.get("/frame/<name>.jpg")
    def still(name):
        """Latest single frame: for ?still=1 mode, when a stream will not play."""
        if name not in STREAMS:
            return jsonify({"error": f"unknown stream {name}"}), 404
        _, jpg = world.frame(name, 0, timeout=0)
        return Response(
            jpg, mimetype="image/jpeg", headers={"Cache-Control": "no-store"}
        )

    @app.post("/api/cube")
    def cube():
        body = request.get_json(silent=True) or {}
        try:
            x, y = float(body["x"]), float(body["y"])
            yaw = float(body.get("yaw_deg", 0.0))
        except (KeyError, TypeError, ValueError):
            return jsonify(
                {"ok": False, "error": "x, y (m), yaw_deg가 필요합니다."}
            ), 400
        return command(world.place_cube, x, y, yaw)

    @app.post("/api/cube/random")
    def cube_random():
        return command(world.random_cube)

    actions = {
        "pick": world.pick,
        "place": world.put_back,
        "home": world.home,
        "stop": world.stop,
        "reset": world.reset,
    }

    @app.post("/api/<action>")
    def act(action):
        if action == "auto":
            enabled = bool((request.get_json(silent=True) or {}).get("enabled"))
            return command(world.set_auto, enabled)
        if action == "speed":
            value = (request.get_json(silent=True) or {}).get("value", 1.0)
            return command(world.set_speed, float(value))
        if action not in actions:
            return jsonify({"ok": False, "error": f"unknown action {action}"}), 404
        return command(actions[action])

    return app


def print_link_when_ready(tunnel: Tunnel, timeout=40.0) -> None:
    end = time.monotonic() + timeout
    while time.monotonic() < end and tunnel.status == "starting":
        time.sleep(0.25)
    if tunnel.status == "on":
        print(
            "\n인터넷 어디서나 (이 링크를 보내세요, 접속 키 포함):\n"
            f"    {tunnel.link()}\n"
            "  · 링크를 가진 사람만 들어올 수 있습니다. 공유를 끄면 링크가 무효가 됩니다.\n"
        )
    else:
        print(f"\n인터넷 공유를 시작하지 못했습니다: {tunnel.error or tunnel.status}\n")


def main(argv=None) -> None:
    p = argparse.ArgumentParser(description="SO-101 pick simulator in the browser")
    p.add_argument(
        "--port",
        type=int,
        default=None,
        help=f"default {DEFAULT_PORT}, or {FALLBACK_PORT} if that cannot be used",
    )
    p.add_argument(
        "--lan",
        action="store_true",
        help="let other computers on the same network open the page",
    )
    p.add_argument(
        "--share",
        action="store_true",
        help="share on the internet through a Cloudflare quick tunnel (key protected)",
    )
    p.add_argument("--host", default=None, help="bind address (default 127.0.0.1)")
    p.add_argument("--open", action="store_true", help="open the browser")
    p.add_argument("--seed", type=int, default=None)
    args = p.parse_args(argv)
    host = args.host or ("0.0.0.0" if args.lan else "127.0.0.1")
    on_lan = host not in ("127.0.0.1", "localhost", "::1")
    if args.port is None:
        args.port = DEFAULT_PORT
        if not port_free(host, DEFAULT_PORT):
            print(f"포트 {DEFAULT_PORT}을 쓸 수 없어 {FALLBACK_PORT}로 엽니다.")
            args.port = FALLBACK_PORT

    world = World(arm.load_profile(), seed=args.seed).start()
    tunnel = Tunnel(args.port)
    atexit.register(tunnel.stop)
    url = http_url("localhost", args.port)
    share = lan_urls(args.port) if on_lan else []
    print(f"\nSO-101 시뮬레이터: {url}  (끝내려면 Ctrl+C 또는 창 닫기)")
    if share:
        print("같은 네트워크의 다른 컴퓨터에서:")
        for u in share:
            print(f"    {u}")
        print(
            "  · 처음 실행 때 macOS가 '들어오는 연결 허용'을 물으면 [허용]을 누르세요.\n"
            "  · 주소를 아는 같은 네트워크의 누구나 조작할 수 있습니다 (시뮬레이터만, 실제 팔 아님)."
        )
    print("인터넷 공유: 페이지 위쪽 [🌐 인터넷 공유] 버튼 (또는 --share)")
    print()
    if args.share:
        tunnel.start()
        threading.Thread(
            target=print_link_when_ready, args=(tunnel,), daemon=True
        ).start()
    if args.open:
        threading.Timer(1.0, webbrowser.open, (url,)).start()
    try:
        create_app(world, share, tunnel).run(
            host=host, port=args.port, threaded=True, debug=False
        )
    finally:
        tunnel.stop()
        world.close()


if __name__ == "__main__":
    main()
