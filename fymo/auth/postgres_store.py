"""PostgresUserStore: the UserStore Protocol on the app's own Postgres.

Enable it in `fymo.yml`:

    auth:
      user_store: fymo.auth.postgres_store.PostgresUserStore

The connection string comes from the DATABASE_URL environment variable, the
same one the procrastinate job provider and the postgres broadcast provider
already read, so identity lands in the database the rest of the app uses.
A missing DATABASE_URL fails at construction, i.e. at boot, never as a lazy
first-request error. The driver is optional; install it with
`pip install 'fymo[postgres]'`.

POSTGRES OBJECTS OWNED BY THIS STORE:
Everything fymo creates is prefixed `fymo_` because it shares the app's
database. The full list (see `schema_postgres.sql`):

    fymo_users                          table
    fymo_users_pkey                     index (implicit, primary key)
    fymo_users_id_seq                   sequence (implicit, owned by fymo_users.id)
    fymo_users_email_lower_idx          unique index on lower(email)
    fymo_user_oauth_identities          table
    fymo_user_oauth_identities_pkey     index (implicit, primary key)

Semantics match SqliteUserStore for every Protocol method: case-insensitive
email uniqueness (EmailAlreadyExists on collision), session_epoch bumping,
idempotent identity linking, and consume-once verify/reset tokens. Two
known divergences, both in Postgres's favor:

  * Case folding is locale-aware here, ASCII-only in SQLite (NOCASE).
    "É@x.com" and "é@x.com" are two distinct users in a SQLite auth.db but
    collide here, so a SQLite database already holding both spellings
    cannot be imported into this store. Pinned by a test in
    tests/auth/test_postgres_store.py.
  * fymo_user_oauth_identities.user_id is an enforced foreign key here;
    SQLite declares it but never enables PRAGMA foreign_keys. Unreachable
    through normal Protocol flows, which always link existing users.

Thread safety comes from a small psycopg_pool ConnectionPool instead of
SqliteUserStore's single-connection lock; each method borrows a pooled
connection for exactly one transaction.
"""
from __future__ import annotations

import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fymo.auth.store import EmailAlreadyExists, User
from fymo.auth.verify_token import hash_token, verify_reset_token, verify_verify_token

_SCHEMA_PATH = Path(__file__).parent / "schema_postgres.sql"
_ENV_VAR = "DATABASE_URL"

# Advisory-lock key serializing schema bootstrap, so several workers booting
# at once don't race the CREATEs. Arbitrary but stable: 'fymo' in ASCII.
_BOOTSTRAP_LOCK_KEY = 0x66796D6F


def _import_psycopg():
    """Import the optional driver with an actionable error, mirroring the
    procrastinate provider: a missing extra must say how to fix itself, not
    dump a ModuleNotFoundError."""
    try:
        import psycopg
        import psycopg_pool
        from psycopg.rows import dict_row
    except ImportError as e:
        raise RuntimeError(
            "PostgresUserStore needs the psycopg package with pool support "
            "(install it with: pip install 'fymo[postgres]')"
        ) from e
    return psycopg, psycopg_pool, dict_row


class PostgresUserStore:
    """UserStore over the app's Postgres. Schema bootstrapped on first connect.

    Same constructor contract as SqliteUserStore: one positional project
    root. It is unused here (the connection comes from $DATABASE_URL) but
    keeps the `auth.user_store` loader working unchanged for every store.
    """

    def __init__(self, project_root: Path):
        self.project_root = Path(project_root)
        url = os.environ.get(_ENV_VAR)
        if not url:
            raise RuntimeError(
                f"PostgresUserStore needs ${_ENV_VAR} set to a Postgres "
                "connection string. It is checked here, at boot, so a "
                "missing URL never surfaces as a first-request failure."
            )
        self._url = url
        self._psycopg, self._psycopg_pool, self._dict_row = _import_psycopg()
        self._lock = threading.Lock()
        self._pool = None

    def _get_pool(self):
        """Open the pool and bootstrap the schema on first use, the pooled
        analogue of SqliteUserStore._connect. Deliberately small with no
        tuning surface: auth traffic is one short transaction per call."""
        if self._pool is None:
            with self._lock:
                if self._pool is None:
                    pool = self._psycopg_pool.ConnectionPool(
                        self._url,
                        min_size=1,
                        max_size=4,
                        open=True,
                        kwargs={"row_factory": self._dict_row},
                    )
                    # If bootstrap fails (transient outage on first call),
                    # close the pool instead of leaking it: its background
                    # workers would keep reconnecting until process exit,
                    # and the next call would build another pool on top.
                    try:
                        with pool.connection() as conn:
                            conn.execute(
                                "SELECT pg_advisory_xact_lock(%s)",
                                (_BOOTSTRAP_LOCK_KEY,),
                            )
                            conn.execute(_SCHEMA_PATH.read_text())
                            self._migrate(conn)
                    except BaseException:
                        pool.close()
                        raise
                    self._pool = pool
        return self._pool

    @staticmethod
    def _migrate(conn) -> None:
        """Additive migrations for databases created before a column existed.

        `CREATE TABLE IF NOT EXISTS` never alters an existing table, so a
        column added to schema_postgres.sql after a database was created
        would be missing. Add it here idempotently; same hook pattern as
        SqliteUserStore._migrate, covering the same columns.
        """
        conn.execute(
            "ALTER TABLE fymo_users "
            "ADD COLUMN IF NOT EXISTS session_epoch INTEGER NOT NULL DEFAULT 1"
        )
        conn.execute(
            "ALTER TABLE fymo_users ADD COLUMN IF NOT EXISTS email_verify_token TEXT"
        )
        conn.execute(
            "ALTER TABLE fymo_users ADD COLUMN IF NOT EXISTS email_verify_sent_at TEXT"
        )
        conn.execute(
            "ALTER TABLE fymo_users ADD COLUMN IF NOT EXISTS password_reset_token TEXT"
        )

    def close(self) -> None:
        """Release pooled connections. Not part of the UserStore Protocol;
        process teardown normally handles it, tests call it explicitly."""
        if self._pool is not None:
            self._pool.close()
            self._pool = None

    @staticmethod
    def _row_to_user(row) -> Optional[User]:
        if row is None:
            return None
        return User(
            id=row["id"],
            email=row["email"],
            password_hash=row["password_hash"],
            email_verified=bool(row["email_verified"]),
            created_at=row["created_at"],
            fymo_uid=row["fymo_uid"],
            session_epoch=row["session_epoch"],
        )

    _COLUMNS = "id, email, password_hash, email_verified, created_at, fymo_uid, session_epoch"

    def get_by_id(self, user_id: int) -> Optional[User]:
        with self._get_pool().connection() as conn:
            row = conn.execute(
                f"SELECT {self._COLUMNS} FROM fymo_users WHERE id = %s",
                (user_id,),
            ).fetchone()
        return self._row_to_user(row)

    def get_by_email(self, email: str) -> Optional[User]:
        with self._get_pool().connection() as conn:
            row = conn.execute(
                f"SELECT {self._COLUMNS} FROM fymo_users "
                "WHERE lower(email) = lower(%s)",
                (email,),
            ).fetchone()
        return self._row_to_user(row)

    def create(self, email: str, password_hash: Optional[str]) -> User:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        try:
            with self._get_pool().connection() as conn:
                row = conn.execute(
                    "INSERT INTO fymo_users (email, password_hash, created_at) "
                    "VALUES (%s, %s, %s) RETURNING id",
                    (email, password_hash, now),
                ).fetchone()
        except self._psycopg.errors.UniqueViolation as e:
            raise EmailAlreadyExists(email) from e
        return User(
            id=row["id"], email=email, password_hash=password_hash,
            email_verified=False, created_at=now, fymo_uid=None,
        )

    def set_password_hash(self, user_id: int, password_hash: str) -> None:
        # Bump the epoch in the same statement so a password change atomically
        # revokes every session issued under the old password.
        with self._get_pool().connection() as conn:
            conn.execute(
                "UPDATE fymo_users "
                "SET password_hash = %s, session_epoch = session_epoch + 1 "
                "WHERE id = %s",
                (password_hash, user_id),
            )

    def bump_session_epoch(self, user_id: int) -> None:
        """Invalidate all outstanding sessions for a user (logout, forced sign-out)."""
        with self._get_pool().connection() as conn:
            conn.execute(
                "UPDATE fymo_users SET session_epoch = session_epoch + 1 "
                "WHERE id = %s",
                (user_id,),
            )

    def get_by_identity(self, provider: str, provider_user_id: str) -> Optional[User]:
        """Return the user linked to an external identity, or None."""
        with self._get_pool().connection() as conn:
            row = conn.execute(
                f"SELECT {self._COLUMNS} FROM fymo_users WHERE id = ("
                "  SELECT user_id FROM fymo_user_oauth_identities"
                "  WHERE provider = %s AND provider_user_id = %s"
                ")",
                (provider, provider_user_id),
            ).fetchone()
        return self._row_to_user(row)

    def link_identity(
        self, user_id: int, provider: str, provider_user_id: str, email: Optional[str]
    ) -> None:
        """Attach an external identity to a user. Idempotent on (provider, sub)."""
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._get_pool().connection() as conn:
            conn.execute(
                "INSERT INTO fymo_user_oauth_identities "
                "(user_id, provider, provider_user_id, email, linked_at) "
                "VALUES (%s, %s, %s, %s, %s) "
                "ON CONFLICT (provider, provider_user_id) DO NOTHING",
                (user_id, provider, provider_user_id, email, now),
            )

    def claim_fymo_uid(self, user_id: int, fymo_uid: str) -> None:
        """Idempotent: only sets fymo_uid if currently NULL."""
        with self._get_pool().connection() as conn:
            conn.execute(
                "UPDATE fymo_users SET fymo_uid = %s "
                "WHERE id = %s AND fymo_uid IS NULL",
                (fymo_uid, user_id),
            )

    def set_verify_token(self, user_id: int, token: str) -> None:
        """Record a newly-issued verification token for `user_id`.

        Only the token's hash is persisted (see `fymo.auth.verify_token`),
        and setting a new token implicitly invalidates any previous
        outstanding one for this user, since the old token's hash no longer
        matches the row, so `consume_verify_token` will reject it even if
        it hasn't expired.
        """
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._get_pool().connection() as conn:
            conn.execute(
                "UPDATE fymo_users "
                "SET email_verify_token = %s, email_verify_sent_at = %s "
                "WHERE id = %s",
                (hash_token(token), now, user_id),
            )

    def consume_verify_token(self, token: str) -> Optional[int]:
        """Validate `token` (signature + expiry) and, if it matches the
        outstanding token hash on record, atomically mark the user verified
        and clear the stored hash so the token can't be replayed. Returns the
        verified user's id, or None if the token is forged, expired, already
        consumed, or superseded by a later `set_verify_token` call."""
        verified = verify_verify_token(token)
        if verified is None:
            return None
        user_id, _issued_at = verified
        with self._get_pool().connection() as conn:
            cur = conn.execute(
                "UPDATE fymo_users "
                "SET email_verified = TRUE, email_verify_token = NULL "
                "WHERE id = %s AND email_verify_token = %s",
                (user_id, hash_token(token)),
            )
            if cur.rowcount == 0:
                return None
        return user_id

    def set_reset_token(self, user_id: int, token: str) -> None:
        """Record a newly-issued password-reset token for `user_id`.

        Only the token's hash is persisted (see `fymo.auth.verify_token`),
        and setting a new token implicitly invalidates any previous
        outstanding one for this user, since the old token's hash no longer
        matches the row, so `consume_reset_token` will reject it even if it
        hasn't expired.
        """
        with self._get_pool().connection() as conn:
            conn.execute(
                "UPDATE fymo_users SET password_reset_token = %s WHERE id = %s",
                (hash_token(token), user_id),
            )

    def consume_reset_token(self, token: str) -> Optional[int]:
        """Validate `token` (signature + expiry) and, if it matches the
        outstanding token hash on record, atomically clear the stored hash so
        the token can't be replayed. Returns the user's id, or None if the
        token is forged, expired, already consumed, or superseded by a later
        `set_reset_token` call. Does NOT change the password itself; the
        caller (`fymo.auth.remote.reset_password`) does that via
        `set_password_hash`, which also bumps `session_epoch` to revoke every
        outstanding session."""
        verified = verify_reset_token(token)
        if verified is None:
            return None
        user_id, _issued_at = verified
        with self._get_pool().connection() as conn:
            cur = conn.execute(
                "UPDATE fymo_users SET password_reset_token = NULL "
                "WHERE id = %s AND password_reset_token = %s",
                (user_id, hash_token(token)),
            )
            if cur.rowcount == 0:
                return None
        return user_id
