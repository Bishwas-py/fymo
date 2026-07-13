"""PostgresBroadcastProvider — LISTEN/NOTIFY as the broadcast transport.

The default provider: needs nothing beyond the Postgres fymo apps already
require, and works across OS processes — a job in the `fymo jobs-worker`
process NOTIFYs, a web worker holding a matching LISTEN picks it up. Same
primitive Procrastinate itself uses for near-instant job pickup.
"""
from __future__ import annotations

import os
import re
import threading
from typing import Iterator, Optional

from fymo.broadcast.providers.base import BaseBroadcastProvider

_DEFAULT_ENV_VAR = "DATABASE_URL"

# Postgres NOTIFY payloads are capped at 8000 bytes by default. Enforced
# loudly at publish time so oversized payloads never silently truncate —
# broadcasts should carry ids and small state, not blobs.
_MAX_PAYLOAD_BYTES = 8000

# LISTEN takes an identifier, not a parameter — the key is interpolated
# into SQL, so it must match the shape channel_key() produces. Anything
# else is rejected before it gets near a query.
_KEY_RE = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


def _import_psycopg():
    try:
        import psycopg
    except ImportError as e:
        raise RuntimeError(
            "the 'postgres' broadcast provider needs the psycopg package — "
            "install it with: pip install 'psycopg[binary]'"
        ) from e
    return psycopg


class PostgresBroadcastProvider(BaseBroadcastProvider):
    id = "postgres"

    def __init__(self, database_url_env: str = _DEFAULT_ENV_VAR) -> None:
        self._database_url_env = database_url_env
        self._publish_conn = None
        self._publish_lock = threading.Lock()

    def publish(self, key: str, payload: str) -> None:
        self._check_key(key)
        size = len(payload.encode("utf-8"))
        if size > _MAX_PAYLOAD_BYTES:
            raise ValueError(
                f"broadcast payload is {size} bytes; Postgres NOTIFY caps at "
                f"{_MAX_PAYLOAD_BYTES}. Publish ids and let subscribers fetch, "
                "not blobs."
            )
        psycopg = _import_psycopg()
        with self._publish_lock:
            try:
                self._publish_conn_or_new().execute(
                    "SELECT pg_notify(%s, %s)", (key, payload)
                )
            except psycopg.OperationalError:
                # Connection died (server restart, idle timeout) — one retry
                # on a fresh connection.
                self._publish_conn = None
                self._publish_conn_or_new().execute(
                    "SELECT pg_notify(%s, %s)", (key, payload)
                )

    def listen(
        self,
        key: str,
        ready: Optional[threading.Event] = None,
        idle_timeout: float = 15.0,
    ) -> Iterator[Optional[str]]:
        """Generator of payloads for `key`, with a `None` idle tick after
        each ~idle_timeout of silence (see BaseBroadcastProvider.listen).
        Runs on its own dedicated connection (LISTEN claims the whole
        connection), closed when the consumer closes the generator (e.g.
        SSE disconnect)."""
        self._check_key(key)
        psycopg = _import_psycopg()
        conn = psycopg.connect(self._database_url(), autocommit=True)
        try:
            conn.execute(f"LISTEN {key}")
            if ready is not None:
                ready.set()
            while True:
                # notifies(timeout=X) yields until the deadline, then the
                # inner generator ends; loop re-enters. The None between
                # windows is the idle tick.
                for notify in conn.notifies(timeout=idle_timeout):
                    yield notify.payload
                yield None
        finally:
            conn.close()

    def _publish_conn_or_new(self):
        if self._publish_conn is None or self._publish_conn.closed:
            psycopg = _import_psycopg()
            self._publish_conn = psycopg.connect(self._database_url(), autocommit=True)
        return self._publish_conn

    def _check_key(self, key: str) -> None:
        if not _KEY_RE.fullmatch(key):
            raise ValueError(f"invalid broadcast channel key: {key!r}")

    def _database_url(self) -> str:
        url = os.environ.get(self._database_url_env)
        if not url:
            raise RuntimeError(
                f"PostgresBroadcastProvider needs ${self._database_url_env} "
                "set to a Postgres connection string"
            )
        return url
