"""Programmatic granian launcher for `fymo serve --prod --server granian`.

Named granian_server (not granian) so importing it never shadows the
granian package itself.

Why this module needs none of the post-fork sidecar dance documented in
fymo/server/gunicorn.py: gunicorn is handed an already-built wsgi app, so
by the time its master forks, a FymoApp (and its Node sidecar, a
subprocess.Popen child spoken to over a length-prefixed pipe) already
exists in the master. Forked workers would inherit that pipe fd, and
siblings reading and writing the same Node process would corrupt the
framing, hence gunicorn.py's careful choreography: stop the master's
sidecar up front, rebuild a worker-owned FymoApp in post_fork, reap it in
worker_exit.

granian inverts the loading model. It is handed a target *string*
("server:app"), and each worker process resolves that string itself
(granian's load_target runs inside the spawned worker, with working_dir
put on sys.path there). The parent that calls run_prod_granian never
imports server.py at all, so no FymoApp and no sidecar ever exist in the
parent, and there is nothing to stop pre-fork or rebuild post-fork. Each
worker's import of server.py builds its own FymoApp and its own Node
child naturally, and FymoApp's own atexit/signal handlers (registered in
its __init__) reap that worker's sidecar when the worker exits. This
holds under both of granian's multiprocessing start methods: with spawn
the worker is a fresh interpreter, and with fork the parent had no
sidecar to leak into the child in the first place.

Within one worker, granian dispatches WSGI calls from multiple blocking
threads. fymo.core.sidecar.Sidecar serializes its pipe protocol with a
threading.Lock, so concurrent threads share the worker's single sidecar
safely (verified under sustained concurrent load in issue #39).
"""
import os
from pathlib import Path


def run_prod_granian(project_root: Path, host: str, port: int, workers: int) -> None:
    """Serve `server:app` from project_root with granian's WSGI interface.

    Blocks until the server is shut down. `workers` is OS processes, the
    same meaning it has for gunicorn. blocking_threads (per-worker WSGI
    dispatch threads) is capped well below granian's derived default,
    which granian itself warns can be excessive for CPU-bound apps.
    """
    from granian import Granian
    from granian.constants import Interfaces

    blocking_threads = min((os.cpu_count() or 1) * 2, 64)

    Granian(
        "server:app",
        address=host,
        port=port,
        interface=Interfaces.WSGI,
        workers=workers,
        blocking_threads=blocking_threads,
        working_dir=project_root,
    ).serve()
