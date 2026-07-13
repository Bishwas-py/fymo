"""Programmatic gunicorn launcher for `fymo serve --prod`.

Each gunicorn worker is a forked OS process. FymoApp owns a Node sidecar
(`fymo.core.sidecar.Sidecar`) talking length-prefixed JSON over a pipe to a
`subprocess.Popen` child; that pipe is a plain file descriptor, so a forked
worker inheriting it would read/write the *same* Node process as its
siblings and corrupt the framing. Every worker must therefore build its own
FymoApp (and therefore its own Node child) *after* it forks, never before.

`preload_app=False` (gunicorn's default, set explicitly here) means gunicorn
does not build the wsgi app before forking. But the `wsgi_app` this module is
handed already exists by the time `run_prod` runs: `fymo serve --prod` builds
it via `server.py`'s module-level `app = create_app(...)`, in the master
process, before any worker forks. That instance's sidecar must never survive
into a worker, so `run_prod` stops it up front, and the `post_fork` hook
builds a fresh, worker-owned FymoApp from the same project root immediately
after each fork — before gunicorn loads the wsgi callable for that worker.
`worker_exit` reaps that worker's sidecar when gunicorn retires the worker.
"""
from gunicorn.app.base import BaseApplication


def _post_fork(server, worker) -> None:
    """Build a fresh, worker-owned FymoApp (and Node sidecar) right after fork.

    Runs inside the forked child, before gunicorn loads the wsgi callable for
    this worker (see `Arbiter.spawn_worker`). Stashes the new app on
    `worker.app_instance` (for `worker_exit` to reap) and on the
    `FymoGunicornApp` instance itself, so `load()` — called moments later in
    this same process — serves the worker-owned app instead of the app built
    in the master before forking.
    """
    gunicorn_app = server.app
    source_app = getattr(gunicorn_app, "_wsgi_app", None)
    project_root = getattr(source_app, "project_root", None)

    if project_root is None:
        # Not a FymoApp (e.g. a plain WSGI callable in a test) — nothing to
        # rebuild per-worker; fall back to whatever we were given.
        worker.app_instance = source_app
        return

    from fymo import create_app
    fresh_app = create_app(project_root, dev=getattr(source_app, "dev", False))
    worker.app_instance = fresh_app
    gunicorn_app._worker_app = fresh_app

    # Note: shutdown() handlers are layered here. The fresh_app's __init__
    # calls _register_shutdown() to install atexit and signal handlers that
    # will call shutdown() on this worker's own app. However, this forked
    # process also inherited the master's shutdown handlers (registered
    # pre-fork), which would try to call shutdown() on the master's app
    # instance. This is safe because: (1) shutdown() is idempotent, and
    # (2) the master's app was already stopped in run_prod() before any
    # workers forked, so the inherited handler fires on an already-stopped
    # sidecar and is a harmless no-op.


def _worker_exit(server, worker) -> None:
    """Stop this worker's own sidecar when gunicorn retires the worker."""
    app = getattr(worker, "app_instance", None)
    if app is None:
        return
    if callable(getattr(app, "shutdown", None)):
        app.shutdown()


class FymoGunicornApp(BaseApplication):
    def __init__(self, wsgi_app, options):
        self._wsgi_app = wsgi_app
        self._options = options
        super().__init__()

    def load_config(self):
        for k, v in self._options.items():
            if v is not None and k in self.cfg.settings:
                self.cfg.set(k, v)

    def load(self):
        # Called once per worker process (preload_app=False). If post_fork
        # already built a worker-owned app in this same process, serve that;
        # otherwise fall back to the app we were constructed with (e.g. a
        # bare WSGI callable in tests that bypass post_fork).
        return getattr(self, "_worker_app", None) or self._wsgi_app


def run_prod(wsgi_app, host: str, port: int, workers: int) -> None:
    # The wsgi_app we were handed was built in this (master/arbiter) process
    # before any worker forked. Its Node sidecar must not be forked into a
    # worker, so stop it here; post_fork builds fresh, worker-owned ones.
    shutdown = getattr(wsgi_app, "shutdown", None)
    if callable(shutdown):
        shutdown()

    FymoGunicornApp(wsgi_app, {
        "bind": f"{host}:{port}",
        "workers": workers,
        "worker_class": "sync",
        "graceful_timeout": 30,
        "preload_app": False,
        "post_fork": _post_fork,
        "worker_exit": _worker_exit,
    }).run()
