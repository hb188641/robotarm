"""A minimal WebSocket server endpoint for Flask's development server.

Why: through the Cloudflare tunnel a long HTTP response (the MJPEG stream) is
delivered in ~128 KB lumps, so the picture jumps once a second or so. WebSocket
messages are passed through one by one, so every frame arrives on its own.

Only what the panel needs: the RFC 6455 handshake, sending text / binary
messages (server frames are never masked), and reading the client's messages
(masked) to answer pings and notice when the page goes away. It uses the raw
socket that Werkzeug's server exposes as environ["werkzeug.socket"].
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import select
import socket
import struct
import threading

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
OP_CONT, OP_TEXT, OP_BINARY, OP_CLOSE, OP_PING, OP_PONG = 0x0, 0x1, 0x2, 0x8, 0x9, 0xA
MAX_INCOMING = 1 << 20  # the browser only sends small control messages


class Closed(Exception):
    """The other side closed the connection (or it broke)."""


def accept_key(key: str) -> str:
    return base64.b64encode(hashlib.sha1((key + GUID).encode()).digest()).decode()


def is_upgrade(environ) -> bool:
    return (
        environ.get("HTTP_UPGRADE", "").lower() == "websocket"
        and "upgrade" in environ.get("HTTP_CONNECTION", "").lower()
        and bool(environ.get("HTTP_SEC_WEBSOCKET_KEY"))
    )


def frame(opcode: int, payload: bytes) -> bytes:
    n = len(payload)
    if n < 126:
        head = struct.pack("!BB", 0x80 | opcode, n)
    elif n < 1 << 16:
        head = struct.pack("!BBH", 0x80 | opcode, 126, n)
    else:
        head = struct.pack("!BBQ", 0x80 | opcode, 127, n)
    return head + payload


class WebSocket:
    def __init__(self, sock: socket.socket):
        self.sock = sock
        self.closed = False
        self._send_lock = threading.Lock()

    @classmethod
    def accept(cls, environ) -> WebSocket | None:
        """Answer the upgrade request; None when this server cannot do it."""
        sock = environ.get("werkzeug.socket")
        if sock is None or not is_upgrade(environ):
            return None
        reply = (
            "HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Accept: {accept_key(environ['HTTP_SEC_WEBSOCKET_KEY'])}\r\n"
            "\r\n"
        )
        sock.sendall(reply.encode())
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        return cls(sock)

    # ---- sending ----
    def _send(self, opcode: int, payload: bytes) -> None:
        if self.closed:
            raise Closed
        try:
            with self._send_lock:
                self.sock.sendall(frame(opcode, payload))
        except OSError as exc:
            self.closed = True
            raise Closed from exc

    def send(self, data: bytes | str) -> None:
        if isinstance(data, str):
            self._send(OP_TEXT, data.encode())
        else:
            self._send(OP_BINARY, bytes(data))

    def close(self, code: int = 1000) -> None:
        if not self.closed:
            try:
                self._send(OP_CLOSE, struct.pack("!H", code))
            except Closed:
                pass
            self.closed = True

    def finish(self) -> None:
        """Close and hang up, so the HTTP server stops reading this socket."""
        self.close()
        with contextlib.suppress(OSError):
            self.sock.shutdown(socket.SHUT_RDWR)

    # ---- receiving ----
    def _read(self, n: int) -> bytes:
        buf = b""
        while len(buf) < n:
            try:
                chunk = self.sock.recv(n - len(buf))
            except OSError as exc:
                raise Closed from exc
            if not chunk:
                raise Closed
            buf += chunk
        return buf

    def _read_frame(self) -> tuple[bool, int, bytes]:
        b0, b1 = self._read(2)
        n = b1 & 0x7F
        if n == 126:
            (n,) = struct.unpack("!H", self._read(2))
        elif n == 127:
            (n,) = struct.unpack("!Q", self._read(8))
        if n > MAX_INCOMING:
            raise Closed
        mask = self._read(4) if b1 & 0x80 else b""
        data = self._read(n)
        if mask:
            data = bytes(c ^ mask[i % 4] for i, c in enumerate(data))
        return bool(b0 & 0x80), b0 & 0x0F, data

    def receive(self, timeout: float | None = None) -> bytes | str | None:
        """Next text/binary message, or None if nothing came within `timeout`.

        Pings are answered and a close frame raises Closed.
        """
        parts: list[bytes] = []
        kind = None
        while True:
            if timeout is not None and not parts:
                ready, _, _ = select.select([self.sock], [], [], timeout)
                if not ready:
                    return None
            fin, opcode, data = self._read_frame()
            if opcode == OP_CLOSE:
                self.close()
                raise Closed
            if opcode == OP_PING:
                self._send(OP_PONG, data)
                continue
            if opcode == OP_PONG:
                continue
            if opcode in (OP_TEXT, OP_BINARY):
                kind, parts = opcode, [data]
            elif opcode == OP_CONT and kind is not None:
                parts.append(data)
            if fin and kind is not None:
                msg = b"".join(parts)
                return msg.decode() if kind == OP_TEXT else msg
