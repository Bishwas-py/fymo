"""Threaded development WSGI server — backs `fymo serve` and `fymo dev`.

Plain `wsgiref.simple_server.make_server` is single-threaded: one
long-lived request (a slow handler, an open SSE broadcast subscription)
freezes every other request, including static assets and page loads. This
factory returns the same wsgiref server with a ThreadingMixIn, so each
request gets its own thread — matching how production gunicorn (gthread)
behaves. Development-only; production stays `fymo serve --prod`.
"""
from __future__ import annotations

from socketserver import ThreadingMixIn
from wsgiref.simple_server import WSGIServer, make_server


class ThreadingWSGIServer(ThreadingMixIn, WSGIServer):
    # Don't let a stuck or long-lived handler thread (e.g. an SSE
    # subscriber that never disconnects) block interpreter exit on Ctrl-C.
    daemon_threads = True


def make_dev_server(host: str, port: int, app) -> WSGIServer:
    """Create the threaded dev server. Same contract as
    `wsgiref.simple_server.make_server` (returns a server; call
    `serve_forever()` on it), but concurrent."""
    return make_server(host, port, app, server_class=ThreadingWSGIServer)
