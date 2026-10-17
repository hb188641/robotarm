"""Exercise the unchanged HTTP client against a local simulator, without hardware."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib
import json
import threading

from TITI.voice_motor.commands import parse_command
from TITI.voice_motor.executor import Executor


def test_existing_http_client_sends_one_batch_and_checks_real_positions():
    positions = {f"motor_{i}": 2100 for i in range(1, 7)}
    traffic = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            traffic.append(("GET", self.path))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(positions).encode())

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            traffic.append(("POST", self.path, body))
            positions.update(body)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(body).encode())

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(
        target=lambda: server.serve_forever(poll_interval=0.01), daemon=True
    )
    worker.start()
    try:
        client = importlib.import_module("TITI.robot_arm_app.클라이언트").로봇팔(
            base_url=f"http://127.0.0.1:{server.server_port}", timeout=1
        )
        limits = {
            f"motor_{i}": {"min": 1800, "max": 2400, "max_delta": 200}
            for i in range(1, 7)
        }
        command = parse_command(
            {"action": "move", "targets": [{"motor": 3, "position": 2200}]}
        )
        assert Executor(client, limits).execute(command) == {"motor_3": 2200}
        assert traffic == [
            ("GET", "/api/state"),
            ("POST", "/api/motors/goal", {"motor_3": 2200}),
            ("GET", "/api/state"),
        ]
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)
