"""Test bootstrapping for apps built on fymo.

A test suite never constructs a FymoApp, so the process-wide seams FymoApp
wires up at startup (the @identify resolver chain, the storage / jobs /
broadcasts provider singletons) are all missing in a bare test process.
This module stands them up for the duration of a block and restores every
registry exactly as it found it, so tests never leak state into each other.

Simulate a signed-in caller for a remote function called directly
(bypassing the WSGI layer):

    from fymo.testing import signed_in
    from app.remote.posts import create_comment

    def test_comment_is_attributed():
        with signed_in("u_alice") as ident:
            comment = create_comment("hello-world", input=NewComment(body="hi"))
            assert comment["uid"] == ident.uid

Prove one identity cannot see or touch another identity's data:

    from fymo.testing import acting_as, signed_in

    def test_other_users_drafts_are_hidden():
        with signed_in("u_alice"):
            draft = create_draft(title="secret")
            with acting_as("u_bob"):
                assert draft["id"] not in [d["id"] for d in get_my_drafts()]

Anonymous requests need no helper at all: open a plain request scope and
current_uid() returns None, exactly as it does for an unrecognized caller:

    from fymo.remote.context import request_scope

    def test_anonymous_cannot_comment():
        with request_scope(uid="u_anon", environ={}):
            assert current_uid() is None

Get get_storage_provider() (plus jobs and broadcasts) working in a test
process, reading the project's own fymo.yml the way FymoApp.__init__ does:

    from fymo.testing import init_providers

    def test_upload(tmp_path):
        with init_providers(project_root):
            get_storage_provider().write("avatars/1.png", data)

signed_in wraps the same @identify + request_scope mechanism fymo uses for
real requests (see fymo.auth.identity and fymo.remote.context); the one
module-level resolver it registers reads the acting identity from a
contextvar, which is what lets sequential and nested blocks each resolve
their own uid (identify() dedups on definition site, so a per-call closure
would collapse to a single stale registration) and what lets acting_as swap
identities mid-block and restore on exit, however deeply nested.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from types import MappingProxyType, SimpleNamespace
from typing import Iterator, Mapping, Optional

from fymo.auth.identity import Identity

__all__ = [
    "signed_in",
    "acting_as",
    "init_providers",
]


# --------------- signed-in identities ---------------

# The identity current_uid() should resolve to right now. None means no
# signed_in block is active. A contextvar (not a plain global) so the
# swap-and-restore semantics of acting_as hold under threads and nesting.
_acting_identity: ContextVar[Optional[Identity]] = ContextVar(
    "fymo_testing_acting_identity", default=None
)

_MISSING = object()


def _testing_identity_resolver(event) -> Optional[Identity]:
    return _acting_identity.get()


def _set_extras(event: dict, extras: Mapping[str, object]) -> None:
    from fymo.auth.context import _EXTRAS_KEY

    event[_EXTRAS_KEY] = MappingProxyType(dict(extras))


@contextmanager
def signed_in(
    uid: str = "u_test1",
    *,
    extras: Optional[Mapping[str, object]] = None,
) -> Iterator[Identity]:
    """Simulate an authenticated caller for the duration of the block.

    Registers an identity resolver through the @identify chain (the exact
    seam app resolvers use, see fymo.auth.identity) that resolves to
    Identity(uid=uid), and opens a request scope so current_uid() and
    request_event() work. Yields the Identity.

    `extras` populates identity_extras() for the scope, standing in for the
    app's extras hooks; identity_extras() returns them read-only, exactly as
    it would the merged hook output on a real request.

    On exit the scope is closed and the resolver chain is restored to the
    snapshot taken at entry, so back-to-back blocks and pre-registered app
    resolvers are never disturbed.
    """
    from fymo.auth import identity as auth_identity
    from fymo.remote.context import _current_event, request_scope

    ident = Identity(uid=uid)
    prior_chain = auth_identity.registered_identity_resolvers()
    auth_identity.identify(_testing_identity_resolver)
    token = _acting_identity.set(ident)
    try:
        # The scope's device uid (fymo.remote.current_uid, the fymo_uid
        # cookie namespace) is deliberately DISTINCT from the identity uid:
        # in a real browser the two never coincide, and code that
        # attributes writes with the wrong accessor should fail here, not
        # in production.
        with request_scope(uid=f"u_device_{uid}", environ={}):
            if extras is not None:
                _set_extras(_current_event.get(), extras)
            yield ident
    finally:
        _acting_identity.reset(token)
        auth_identity.reset_identity_resolvers()
        for resolver in prior_chain:
            auth_identity.identify(resolver)


@contextmanager
def acting_as(
    uid: str,
    *,
    extras: Optional[Mapping[str, object]] = None,
) -> Iterator[Identity]:
    """Swap the resolved identity to Identity(uid=uid) for the block.

    Swaps the full identity: current_uid() resolves to `uid` (the per-scope
    resolution cache is invalidated so the swap wins even after the outer
    identity already resolved), and identity_extras() follows the new
    identity: it returns `extras` when given and is empty otherwise, never
    the enclosing identity's extras. Leaking the outer extras would be a
    false pass for exactly the authorization tests this API exists for.

    Must be entered inside a signed_in() block; the enclosing identity,
    cached resolution, and extras are restored on exit, even when the block
    raises. Nests freely: each exit restores the enclosing block's identity.
    """
    from fymo.auth.context import _EXTRAS_KEY
    from fymo.auth.identity import _RESOLUTION_KEY
    from fymo.remote.context import _current_event

    if _acting_identity.get() is None:
        raise RuntimeError(
            "acting_as() requires an enclosing signed_in() block; "
            "wrap the test body in `with signed_in(...):` first"
        )
    event = _current_event.get()
    ident = Identity(uid=uid)
    prior_uid = event["uid"]
    prior_resolution = event.pop(_RESOLUTION_KEY, _MISSING)
    prior_extras = event.pop(_EXTRAS_KEY, _MISSING)
    token = _acting_identity.set(ident)
    event["uid"] = uid
    if extras is not None:
        _set_extras(event, extras)
    try:
        yield ident
    finally:
        _acting_identity.reset(token)
        event["uid"] = prior_uid
        if prior_resolution is _MISSING:
            event.pop(_RESOLUTION_KEY, None)
        else:
            event[_RESOLUTION_KEY] = prior_resolution
        if prior_extras is _MISSING:
            event.pop(_EXTRAS_KEY, None)
        else:
            event[_EXTRAS_KEY] = prior_extras


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
