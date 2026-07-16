"""UserStore Protocol + the default SQLite implementation.

App authors swap the implementation via `fymo.yml`. fymo ships two: this
module's SqliteUserStore (the default) and
`fymo.auth.postgres_store.PostgresUserStore`, which keeps identity in the
same Postgres database the rest of the app uses:

    auth:
      user_store: fymo.auth.postgres_store.PostgresUserStore

The class is instantiated with a single positional argument: the project
root path. Anything else (DB URL, schema name, etc.) should come from the
custom store's environment or config.
"""
from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Protocol, runtime_checkable

from fymo.auth.verify_token import hash_token, verify_reset_token, verify_verify_token

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"


@dataclass(frozen=True)
class User:
    id: int
    email: str
    password_hash: Optional[str]
    email_verified: bool
    created_at: str
    fymo_uid: Optional[str] = None
    # Monotonic per-user counter. A session token carries the epoch it was
    # minted under; bumping this (logout, password change) revokes every token
    # issued before the bump.
    session_epoch: int = 1


class EmailAlreadyExists(Exception):
    """Raised by UserStore.create() when the email collides with an existing row."""


@runtime_checkable
class UserStore(Protocol):
    """The storage interface every implementation must satisfy."""

    def get_by_id(self, user_id: int) -> Optional[User]: ...
    def get_by_email(self, email: str) -> Optional[User]: ...
    def create(self, email: str, password_hash: Optional[str]) -> User: ...
    def set_password_hash(self, user_id: int, password_hash: str) -> None: ...
    def claim_fymo_uid(self, user_id: int, fymo_uid: str) -> None: ...
    def bump_session_epoch(self, user_id: int) -> None: ...
    def get_by_identity(self, provider: str, provider_user_id: str) -> Optional[User]: ...
    def link_identity(
        self, user_id: int, provider: str, provider_user_id: str, email: Optional[str]
    ) -> None: ...
    def set_verify_token(self, user_id: int, token: str) -> None: ...
    def consume_verify_token(self, token: str) -> Optional[int]: ...
    def set_reset_token(self, user_id: int, token: str) -> None: ...
    def consume_reset_token(self, token: str) -> Optional[int]: ...


class SqliteUserStore:
    """Default store. One SQLite file at `app/data/auth.db`, schema bootstrapped on first connect."""

    def __init__(self, project_root: Path):
        self.project_root = Path(project_root)
        self._path = self.project_root / "app" / "data" / "auth.db"
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn: Optional[sqlite3.Connection] = None

    def _connect(self) -> sqlite3.Connection:
        if self._conn is None:
            conn = sqlite3.connect(str(self._path), check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.executescript(_SCHEMA_PATH.read_text())
            self._migrate(conn)
            conn.commit()
            self._conn = conn
        return self._conn

    @staticmethod
    def _migrate(conn: sqlite3.Connection) -> None:
        """Additive migrations for DBs created before a column existed.

        `CREATE TABLE IF NOT EXISTS` never alters an existing table, so a
        column added to schema.sql after a user's DB was created would be
        missing. Add it here idempotently.
        """
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(fymo_users)")}
        if "session_epoch" not in cols:
            conn.execute(
                "ALTER TABLE fymo_users ADD COLUMN session_epoch INTEGER NOT NULL DEFAULT 1"
            )
        if "email_verify_token" not in cols:
            conn.execute("ALTER TABLE fymo_users ADD COLUMN email_verify_token TEXT")
        if "email_verify_sent_at" not in cols:
            conn.execute("ALTER TABLE fymo_users ADD COLUMN email_verify_sent_at TEXT")
        if "password_reset_token" not in cols:
            conn.execute("ALTER TABLE fymo_users ADD COLUMN password_reset_token TEXT")

    def _row_to_user(self, row: Optional[sqlite3.Row]) -> Optional[User]:
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
        with self._lock:
            cur = self._connect().execute(
                f"SELECT {self._COLUMNS} FROM fymo_users WHERE id = ?",
                (user_id,),
            )
            return self._row_to_user(cur.fetchone())

    def get_by_email(self, email: str) -> Optional[User]:
        with self._lock:
            cur = self._connect().execute(
                f"SELECT {self._COLUMNS} FROM fymo_users WHERE email = ? COLLATE NOCASE",
                (email,),
            )
            return self._row_to_user(cur.fetchone())

    def create(self, email: str, password_hash: Optional[str]) -> User:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._lock:
            try:
                cur = self._connect().execute(
                    "INSERT INTO fymo_users (email, password_hash, created_at) "
                    "VALUES (?, ?, ?)",
                    (email, password_hash, now),
                )
                self._connect().commit()
            except sqlite3.IntegrityError as e:
                if "UNIQUE" in str(e):
                    raise EmailAlreadyExists(email) from e
                raise
            user_id = cur.lastrowid
            assert user_id is not None
        return User(
            id=user_id, email=email, password_hash=password_hash,
            email_verified=False, created_at=now, fymo_uid=None,
        )

    def set_password_hash(self, user_id: int, password_hash: str) -> None:
        # Bump the epoch in the same statement so a password change atomically
        # revokes every session issued under the old password.
        with self._lock:
            conn = self._connect()
            conn.execute(
                "UPDATE fymo_users SET password_hash = ?, session_epoch = session_epoch + 1 "
                "WHERE id = ?",
                (password_hash, user_id),
            )
            conn.commit()

    def bump_session_epoch(self, user_id: int) -> None:
        """Invalidate all outstanding sessions for a user (logout, forced sign-out)."""
        with self._lock:
            conn = self._connect()
            conn.execute(
                "UPDATE fymo_users SET session_epoch = session_epoch + 1 WHERE id = ?",
                (user_id,),
            )
            conn.commit()

    def get_by_identity(self, provider: str, provider_user_id: str) -> Optional[User]:
        """Return the user linked to an external identity, or None."""
        with self._lock:
            cur = self._connect().execute(
                f"SELECT {self._COLUMNS} FROM fymo_users WHERE id = ("
                "  SELECT user_id FROM fymo_user_oauth_identities"
                "  WHERE provider = ? AND provider_user_id = ?"
                ")",
                (provider, provider_user_id),
            )
            return self._row_to_user(cur.fetchone())

    def link_identity(
        self, user_id: int, provider: str, provider_user_id: str, email: Optional[str]
    ) -> None:
        """Attach an external identity to a user. Idempotent on (provider, sub)."""
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._lock:
            conn = self._connect()
            conn.execute(
                "INSERT INTO fymo_user_oauth_identities "
                "(user_id, provider, provider_user_id, email, linked_at) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(provider, provider_user_id) DO NOTHING",
                (user_id, provider, provider_user_id, email, now),
            )
            conn.commit()

    def claim_fymo_uid(self, user_id: int, fymo_uid: str) -> None:
        """Idempotent: only sets fymo_uid if currently NULL."""
        with self._lock:
            self._connect().execute(
                "UPDATE fymo_users SET fymo_uid = ? WHERE id = ? AND fymo_uid IS NULL",
                (fymo_uid, user_id),
            )
            self._connect().commit()

    def set_verify_token(self, user_id: int, token: str) -> None:
        """Record a newly-issued verification token for `user_id`.

        Only the token's hash is persisted (see `fymo.auth.verify_token`), and
        setting a new token implicitly invalidates any previous outstanding
        one for this user — the old token's hash no longer matches the row,
        so `consume_verify_token` will reject it even if it hasn't expired.
        """
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._lock:
            conn = self._connect()
            conn.execute(
                "UPDATE fymo_users SET email_verify_token = ?, email_verify_sent_at = ? "
                "WHERE id = ?",
                (hash_token(token), now, user_id),
            )
            conn.commit()

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
        with self._lock:
            conn = self._connect()
            cur = conn.execute(
                "UPDATE fymo_users SET email_verified = 1, email_verify_token = NULL "
                "WHERE id = ? AND email_verify_token = ?",
                (user_id, hash_token(token)),
            )
            conn.commit()
            if cur.rowcount == 0:
                return None
        return user_id

    def set_reset_token(self, user_id: int, token: str) -> None:
        """Record a newly-issued password-reset token for `user_id`.

        Only the token's hash is persisted (see `fymo.auth.verify_token`), and
        setting a new token implicitly invalidates any previous outstanding
        one for this user — the old token's hash no longer matches the row,
        so `consume_reset_token` will reject it even if it hasn't expired.
        """
        with self._lock:
            conn = self._connect()
            conn.execute(
                "UPDATE fymo_users SET password_reset_token = ? WHERE id = ?",
                (hash_token(token), user_id),
            )
            conn.commit()

    def consume_reset_token(self, token: str) -> Optional[int]:
        """Validate `token` (signature + expiry) and, if it matches the
        outstanding token hash on record, atomically clear the stored hash so
        the token can't be replayed. Returns the user's id, or None if the
        token is forged, expired, already consumed, or superseded by a later
        `set_reset_token` call. Does NOT change the password itself — the
        caller (`fymo.auth.remote.reset_password`) does that via
        `set_password_hash`, which also bumps `session_epoch` to revoke every
        outstanding session."""
        verified = verify_reset_token(token)
        if verified is None:
            return None
        user_id, _issued_at = verified
        with self._lock:
            conn = self._connect()
            cur = conn.execute(
                "UPDATE fymo_users SET password_reset_token = NULL "
                "WHERE id = ? AND password_reset_token = ?",
                (user_id, hash_token(token)),
            )
            conn.commit()
            if cur.rowcount == 0:
                return None
        return user_id
