"""Persistent Node sidecar IPC client.

Python <-> Node protocol: length-prefixed JSON frames on stdio.
Frame format: [4-byte big-endian length][UTF-8 JSON payload of that length]

Resilience:
- Auto-restarts the Node child on broken-pipe / closed-stdout (one retry per
  user call). The most common cause is the child crashing on a render error
  that left it in a bad state. Restart + retry recovers the in-flight call.
- Per-call timeout. If Node hangs (infinite loop in a Svelte component, GC
  pause, deadlock), the watchdog kills the child after `timeout` seconds and
  surfaces a SidecarError to the WSGI worker. The retry loop will then spin
  up a fresh process for any subsequent call.
- Caller can opt out by passing timeout=None.
"""
import itertools
import json
import os
import select
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

    def __init__(self, dist_dir: Path, timeout: Optional[float] = 30.0):
        """
        Args:
            dist_dir: Directory containing the built `sidecar.mjs`.
            timeout: Per-call timeout in seconds. None disables timeout (not
                recommended in production — a hung child blocks the WSGI
                worker forever). Default 30s is safe for most SSR workloads.
        """
        self.dist_dir = Path(dist_dir).resolve()
        self.script = self.dist_dir / "sidecar.mjs"
        self.timeout = timeout
        self._proc: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self._next_id = itertools.count(1)
        self._restart_count = 0  # for tests + observability

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
        proc = self._proc
        self._proc = None
        if proc is None:
            return
        try:
            if proc.stdin and not proc.stdin.closed:
                proc.stdin.close()
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
                proc.wait(timeout=1)
            except Exception:
                pass
        except Exception:
            pass

    def ping(self) -> bool:
        reply = self._send({"type": "ping"})
        return reply.get("ok") is True

    def render(self, route: str, props: Dict[str, Any], doc: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
        msg: Dict[str, Any] = {"type": "render", "route": route, "props": props}
        if doc is not None:
            msg["doc"] = doc
        reply = self._send(msg)
        return {"body": reply["body"], "head": reply["head"]}

    # ---------------- IPC ----------------

    def _send(self, msg: Dict[str, Any]) -> Dict[str, Any]:
        msg_id = next(self._next_id)
        msg["id"] = msg_id
        body = json.dumps(msg).encode("utf-8")
        frame = struct.pack(">I", len(body)) + body

        with self._lock:
            payload, last_err = None, None
            for attempt in range(2):  # 1 retry on transient IPC failure / timeout
                self._ensure_running_locked()
                try:
                    payload = self._send_frame_locked(frame)
                    break
                except (BrokenPipeError, OSError, _Timeout) as e:
                    last_err = e
                    self._kill_proc_locked()
                    continue
            if payload is None:
                raise SidecarError(f"sidecar IPC failed after retry: {last_err}")

        reply = json.loads(payload.decode("utf-8"))
        if not reply.get("ok"):
            raise SidecarError(reply.get("error", "unknown sidecar error"), reply.get("stack", ""))
        return reply

    def _send_frame_locked(self, frame: bytes) -> bytes:
        """Write `frame`, wait for response, return body bytes. Caller holds lock + proc alive."""
        assert self._proc is not None and self._proc.stdin is not None and self._proc.stdout is not None
        self._proc.stdin.write(frame)
        self._proc.stdin.flush()
        if self.timeout is not None:
            ready, _, _ = select.select([self._proc.stdout], [], [], self.timeout)
            if not ready:
                raise _Timeout(f"sidecar render exceeded {self.timeout}s")
        length_bytes = self._read_exact_locked(4)
        (length,) = struct.unpack(">I", length_bytes)
        return self._read_exact_locked(length)

    def _read_exact_locked(self, n: int) -> bytes:
        assert self._proc is not None and self._proc.stdout is not None
        buf = b""
        while len(buf) < n:
            chunk = self._proc.stdout.read(n - len(buf))
            if not chunk:
                raise BrokenPipeError("sidecar stdout closed")
            buf += chunk
        return buf

    # ---------------- lifecycle helpers ----------------

    def _ensure_running_locked(self) -> None:
        """Restart the sidecar if it's dead. Caller must hold self._lock."""
        if self._proc is None or self._proc.poll() is not None:
            self._proc = None
            self.start()
            self._restart_count += 1

    def _kill_proc_locked(self) -> None:
        proc = self._proc
        self._proc = None
        if proc is None:
            return
        try:
            proc.kill()
        except Exception:
            pass
        try:
            proc.wait(timeout=1)
        except Exception:
            pass


class _Timeout(Exception):
    """Internal sentinel — caught by _send and converted to a retry/SidecarError."""
