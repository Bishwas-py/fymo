"""Tests for fymo.server.dev.make_dev_server — the threaded wsgiref server
behind `fymo serve` and `fymo dev`.

The old single-threaded wsgiref server meant ONE slow request (a long
agent job before job providers, an open SSE subscription once broadcasts
land) froze every other request. The dev server must serve concurrently.
"""
import threading
import time
import urllib.request

import pytest

from fymo.server.dev import make_dev_server


def _app(environ, start_response):
    path = environ.get("PATH_INFO", "/")
    if path == "/slow":
        time.sleep(2)
        body = b"slow done"
    else:
        body = b"fast done"
    start_response("200 OK", [("Content-Type", "text/plain"), ("Content-Length", str(len(body)))])
    return [body]


@pytest.fixture
def server():
    httpd = make_dev_server("127.0.0.1", 0, _app)  # port 0: pick a free port
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd
    httpd.shutdown()


def _get(port: int, path: str) -> bytes:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as res:
        return res.read()


def test_serves_a_request(server):
    port = server.server_address[1]
    assert _get(port, "/fast") == b"fast done"


def test_fast_request_is_not_blocked_by_a_slow_one(server):
    """The regression this exists to prevent: with the old single-threaded
    server, /fast would wait the full 2s behind /slow."""
    port = server.server_address[1]

    slow_started = threading.Event()

    def hit_slow():
        slow_started.set()
        _get(port, "/slow")

    slow_thread = threading.Thread(target=hit_slow, daemon=True)
    slow_thread.start()
    slow_started.wait(timeout=2)
    time.sleep(0.2)  # let /slow actually reach the handler's sleep

    t0 = time.monotonic()
    assert _get(port, "/fast") == b"fast done"
    elapsed = time.monotonic() - t0

    assert elapsed < 1.0, (
        f"/fast took {elapsed:.2f}s — it queued behind /slow, "
        "so the server is not serving concurrently"
    )
    slow_thread.join(timeout=5)


def test_threads_are_daemonic_so_stuck_handlers_never_block_exit(server):
    assert server.daemon_threads is True
