"""Persistent Node sidecar IPC client.

Python <-> Node protocol: length-prefixed JSON frames on stdio.
Frame format: [4-byte big-endian length][UTF-8 JSON payload of that length]
"""
import itertools
import json
import struct
import subprocess
import threading
from pathlib import Path
from typing import Any, Dict, Optional


class SidecarError(RuntimeError):
    """Raised when the sidecar reports an error or is unavailable."""

    def __init__(self, message: str, stack: str = ""):
        super().__init__(message)
        self.stack = stack


class Sidecar:
    """Long-lived Node SSR sidecar managed from Python."""

    def __init__(self, dist_dir: Path):
        self.dist_dir = Path(dist_dir).resolve()
        self.script = self.dist_dir / "sidecar.mjs"
        self._proc: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self._next_id = itertools.count(1)

    def start(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            return
        if not self.script.is_file():
            raise SidecarError(f"sidecar script not found at {self.script}; run `fymo build` first")
        self._proc = subprocess.Popen(
            ["node", str(self.script)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=None,  # inherit so logs surface
            cwd=str(self.dist_dir),
        )

    def stop(self) -> None:
        if self._proc is None:
            return
        try:
            self._proc.stdin.close()
            self._proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self._proc.kill()
            self._proc.wait()
        finally:
            self._proc = None

    def ping(self) -> bool:
        reply = self._send({"type": "ping"})
        return reply.get("ok") is True

    def render(self, route: str, props: Dict[str, Any], doc: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
        msg: Dict[str, Any] = {"type": "render", "route": route, "props": props}
        if doc is not None:
            msg["doc"] = doc
        reply = self._send(msg)
        return {"body": reply["body"], "head": reply["head"]}

    def _send(self, msg: Dict[str, Any]) -> Dict[str, Any]:
        if self._proc is None or self._proc.poll() is not None:
            raise SidecarError("sidecar not running; call start() first")

        msg_id = next(self._next_id)
        msg["id"] = msg_id
        body = json.dumps(msg).encode("utf-8")
        frame = struct.pack(">I", len(body)) + body

        with self._lock:
            try:
                self._proc.stdin.write(frame)
                self._proc.stdin.flush()
                length_bytes = self._read_exact(4)
                (length,) = struct.unpack(">I", length_bytes)
                payload = self._read_exact(length)
            except (BrokenPipeError, OSError) as e:
                raise SidecarError(f"sidecar IPC failure: {e}")

        reply = json.loads(payload.decode("utf-8"))
        if not reply.get("ok"):
            raise SidecarError(reply.get("error", "unknown sidecar error"), reply.get("stack", ""))
        return reply

    def _read_exact(self, n: int) -> bytes:
        buf = b""
        while len(buf) < n:
            chunk = self._proc.stdout.read(n - len(buf))
            if not chunk:
                raise SidecarError("sidecar stdout closed")
            buf += chunk
        return buf
