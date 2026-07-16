"""Test bootstrapping for apps built on fymo.

A test suite never constructs a FymoApp, so the process-wide seams FymoApp
wires up at startup (the auth session-resolver chain, the storage / jobs /
broadcasts provider singletons) are all missing in a bare test process.
This module stands them up for the duration of a block and restores every
registry exactly as it found it, so tests never leak state into each other.

Simulate a signed-in caller for a remote function called directly
(bypassing the WSGI layer):

    from fymo.testing import signed_in
    from app.remote.posts import create_comment

    def test_comment_is_attributed():
        with signed_in() as user:
            comment = create_comment("hello-world", input=NewComment(body="hi"))
            assert comment["name"] == user.email.split("@")[0]

Prove one user cannot see or touch another user's data:

    from fymo.testing import acting_as, make_user, signed_in

    def test_other_users_drafts_are_hidden():
        alice = make_user(email="alice@example.com")
        bob = make_user(email="bob@example.com")
        with signed_in(alice):
            draft = create_draft(title="secret")
            with acting_as(bob):
                assert draft["id"] not in [d["id"] for d in get_my_drafts()]

Get get_storage_provider() (plus jobs and broadcasts) working in a test
process, reading the project's own fymo.yml the way FymoApp.__init__ does:

    from fymo.testing import init_providers

    def test_upload(tmp_path):
        with init_providers(project_root):
            get_storage_provider().write("avatars/1.png", data)

`signed_in` wraps the same register_session_resolver + request_scope
mechanism fymo's router uses for real requests (see fymo.auth.context and
fymo.remote.context); the resolver it registers reads the acting user from
a contextvar, which is what lets `acting_as` swap identities mid-block and
restore on exit, however deeply nested.

The uid rule: the anonymous-identity uid (current_uid()) always follows
the acting user, derived as "u_test{user.id}", so different users never
share uid-keyed data (reactions, anonymous attribution) any more than two
real browsers would. Both signed_in and acting_as take uid= when a test
needs an exact value.

Importable without pytest. When pytest is installed, the `signed_in_user`
fixture at the bottom is also available; re-export it from a conftest.py to
use it:

    from fymo.testing import signed_in_user  # noqa: F401
"""
from __future__ import annotations

import itertools
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Iterator, Optional

from fymo.auth.store import User

__all__ = [
    "make_user",
    "signed_in",
    "acting_as",
    "init_providers",
]


# --------------- fake users ---------------

_next_user_id = itertools.count(1)


def make_user(email: str = "test@example.com", **overrides) -> User:
    """Build a real fymo User with sensible test defaults.

    Every field of fymo.auth.store.User can be overridden by keyword; ids
    auto-increment per process so two default users never collide.
    """
    fields = {
        "id": next(_next_user_id),
        "email": email,
        "password_hash": None,
        "email_verified": True,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "fymo_uid": None,
        "session_epoch": 1,
    }
    fields.update(overrides)
    return User(**fields)


# --------------- signed-in sessions ---------------

# The user current_user() should resolve to right now. None means no
# signed_in block is active. A contextvar (not a plain global) so the
# swap-and-restore semantics of acting_as hold under threads and nesting.
_acting_user: ContextVar[Optional[User]] = ContextVar(
    "fymo_testing_acting_user", default=None
)


def _uid_for(user: User) -> str:
    return f"u_test{user.id}"


def _testing_resolver(event: dict) -> Optional[User]:
    return _acting_user.get()


@contextmanager
def signed_in(
    user: Optional[User] = None,
    *,
    uid: Optional[str] = None,
    environ: Optional[dict] = None,
) -> Iterator[User]:
    """Simulate an authenticated caller for the duration of the block.

    Registers a session resolver (the exact mechanism providers use, see
    fymo.auth.context.register_session_resolver) that resolves to `user`,
    and opens a remote-function request scope so current_user(),
    current_uid(), and request_event() all work. Yields the user; pass one
    from make_user() to customize it, or omit it for a default.

    The uid rule: identity is user plus uid, and the uid follows the user.
    It defaults to "u_test{user.id}" so two different users never share a
    uid (uid-keyed app data, like reaction rows, stays isolated per user
    the way it would be for real browsers); pass `uid` explicitly when a
    test cares about the exact value. `environ` is a WSGI-shaped dict for
    tests that need specific headers or cookies visible to resolvers.

    On exit the resolver is removed and the scope closed, leaving the
    resolver registry exactly as it was found.
    """
    from fymo.auth import context as auth_context
    from fymo.remote.context import request_scope

    if user is None:
        user = make_user()
    if uid is None:
        uid = _uid_for(user)
    auth_context.register_session_resolver(_testing_resolver)
    token = _acting_user.set(user)
    try:
        with request_scope(uid=uid, environ=dict(environ or {})):
            yield user
    finally:
        _acting_user.reset(token)
        try:
            auth_context._session_resolvers.remove(_testing_resolver)
        except ValueError:
            pass  # reset_session_resolvers() already dropped it mid-block


@contextmanager
def acting_as(user: User, *, uid: Optional[str] = None) -> Iterator[User]:
    """Swap the resolved identity to `user` for the duration of the block.

    Swaps the FULL identity: current_user() resolves to `user`, and the
    request scope's uid (what current_uid() returns) follows the same rule
    as signed_in, defaulting to "u_test{user.id}" unless `uid` is given.
    Swapping only the user would let uid-keyed app data leak between the
    two identities, a false pass for exactly the authorization tests this
    API exists for.

    Must be entered inside a signed_in() block; the previously signed-in
    user and uid are restored on exit, even when the block raises. Nests
    freely: each exit restores the identity of the enclosing block.
    """
    from fymo.remote.context import _current_event

    if _acting_user.get() is None:
        raise RuntimeError(
            "acting_as() requires an enclosing signed_in() block; "
            "wrap the test body in `with signed_in(...):` first"
        )
    event = _current_event.get()
    prior_uid = event["uid"]
    token = _acting_user.set(user)
    event["uid"] = uid if uid is not None else _uid_for(user)
    try:
        yield user
    finally:
        event["uid"] = prior_uid
        _acting_user.reset(token)


# --------------- provider bootstrap ---------------


@contextmanager
def init_providers(project_root: Path) -> Iterator[SimpleNamespace]:
    """Initialize storage, jobs, and broadcasts providers from the
    project's fymo.yml, mirroring what FymoApp.__init__ does at startup.

    Storage is initialized only when fymo.yml has a `storage:` section
    (there is no default provider, matching FymoApp); jobs and broadcasts
    are always initialized, with the same defaults FymoApp uses. Yields a
    namespace with the built providers (`.storage` is None when storage is
    unconfigured); app code reaches them the normal way, via
    get_storage_provider() / get_job_provider() / publish().

    On exit every provider singleton is restored to exactly what it was
    before the block, installed or not, so back-to-back tests can't leak
    providers into each other.

    Raises FileNotFoundError when project_root has no fymo.yml: a test
    pointing at the wrong directory should fail loudly, not run against an
    empty config.
    """
    import fymo.broadcast as broadcast_mod
    import fymo.jobs as jobs_mod
    import fymo.storage as storage_mod
    from fymo.core.config import ConfigManager

    project_root = Path(project_root)
    if not (project_root / "fymo.yml").is_file():
        raise FileNotFoundError(
            f"no fymo.yml found in {project_root}; init_providers() takes "
            "the project root directory, the same one FymoApp would run from"
        )

    config_manager = ConfigManager(project_root)

    prior_storage = storage_mod._provider
    prior_jobs = jobs_mod._job_provider
    prior_broadcast_provider = broadcast_mod._provider
    prior_broadcast_channels = broadcast_mod._channels

    try:
        storage_config = config_manager.get_storage_config()
        storage = None
        if storage_config is not None:
            storage = storage_mod.init_storage_provider(project_root, storage_config)
        jobs = jobs_mod.init_job_provider(
            project_root, config_manager.get_jobs_config().get("provider")
        )
        broadcasts = broadcast_mod.init_broadcasts(
            project_root, config_manager.get_broadcasts_config().get("provider")
        )
        yield SimpleNamespace(storage=storage, jobs=jobs, broadcasts=broadcasts)
    finally:
        storage_mod.set_storage_provider(prior_storage)
        jobs_mod.set_job_provider(prior_jobs)
        with broadcast_mod._lock:
            broadcast_mod._provider = prior_broadcast_provider
            broadcast_mod._channels = prior_broadcast_channels


# --------------- optional pytest fixtures ---------------
#
# fymo does not depend on pytest at runtime, so the fixtures only exist
# when pytest is importable. Everything above stays plain context managers
# usable from any test runner.

try:
    import pytest as _pytest
except ImportError:  # pragma: no cover
    _pytest = None

if _pytest is not None:
    __all__.append("signed_in_user")

    @_pytest.fixture
    def signed_in_user() -> Iterator[User]:
        """A default signed-in user for the whole test. Re-export from your
        conftest.py: `from fymo.testing import signed_in_user  # noqa: F401`"""
        with signed_in() as user:
            yield user
