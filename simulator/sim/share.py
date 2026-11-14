"""Internet sharing without port forwarding: a Cloudflare quick tunnel + a key.

`cloudflared tunnel --url http://127.0.0.1:PORT` makes an outbound connection
to Cloudflare and gets a random public https://<words>.trycloudflare.com
address that forwards to this computer. No account, router setup or port
forwarding is needed. Anyone on the internet can reach that address, so every
request that arrives through the tunnel must carry the access key (from the
shared link, then a cookie). Turning sharing off and on makes a new address
and a new key, which revokes old links.
"""

from __future__ import annotations

import hmac
import re
import secrets
import shutil
import subprocess
import threading

URL_PATTERN = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
COOKIE = "sim_key"


def new_key() -> str:
    """12 URL-safe characters (72 bits): unguessable, still short enough to type."""
    return secrets.token_urlsafe(9)


def key_matches(given: str | None, expected: str | None) -> bool:
    if not given or not expected:
        return False
    return hmac.compare_digest(given.encode(), expected.encode())


def via_tunnel(headers, host: str) -> bool:
    """True for requests that came in from the internet through Cloudflare.

    cloudflared connects to us from 127.0.0.1, so the peer address cannot tell;
    Cloudflare always sets Cf-Connecting-Ip / Cf-Ray, and the Host is the
    tunnel's trycloudflare.com name.
    """
    hostname = host.split(":")[0].lower()
    return (
        "Cf-Connecting-Ip" in headers
        or "Cf-Ray" in headers
        or hostname.endswith(".trycloudflare.com")
    )


class Tunnel:
    """One cloudflared quick tunnel process; start/stop from any thread."""

    def __init__(self, port: int, binary: str | None = None):
        self.port = port
        self.binary = binary or shutil.which("cloudflared")
        self._lock = threading.Lock()
        self._proc: subprocess.Popen | None = None
        self.url: str | None = None
        self.key: str | None = None
        self.status = "off"  # off | starting | on | error
        self.error = ""

    @property
    def available(self) -> bool:
        return self.binary is not None

    def link(self) -> str | None:
        if self.status == "on" and self.url and self.key:
            return f"{self.url}/?key={self.key}"
        return None

    def info(self) -> dict:
        return {
            "available": self.available,
            "status": self.status,
            "url": self.url if self.status == "on" else None,
            "link": self.link(),
            "error": self.error,
        }

    def start(self) -> None:
        with self._lock:
            if self.status in ("starting", "on"):
                return
            if not self.available:
                self.status, self.error = (
                    "error",
                    "cloudflared가 없습니다. 터미널에서 brew install cloudflared",
                )
                return
            self.key = new_key()
            self.url, self.error, self.status = None, "", "starting"
            self._proc = subprocess.Popen(
                [
                    self.binary,
                    "tunnel",
                    "--no-autoupdate",
                    "--url",
                    f"http://127.0.0.1:{self.port}",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
            )
            proc = self._proc
        threading.Thread(target=self._watch, args=(proc,), daemon=True).start()

    def _watch(self, proc: subprocess.Popen) -> None:
        """Read cloudflared's log for the public URL; note when it dies."""
        tail: list[str] = []
        for line in proc.stderr:
            tail = (tail + [line.strip()])[-5:]
            found = URL_PATTERN.search(line)
            if found:
                with self._lock:
                    if self._proc is proc and self.status == "starting":
                        self.url, self.status = found.group(0), "on"
        proc.wait()
        with self._lock:
            if self._proc is proc and self.status != "off":
                self.status = "error"
                self.error = "터널이 끊겼습니다: " + (
                    tail[-1] if tail else "cloudflared 종료"
                )
                self._proc = None

    def stop(self) -> None:
        with self._lock:
            proc, self._proc = self._proc, None
            self.status, self.url, self.key, self.error = "off", None, None, ""
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
