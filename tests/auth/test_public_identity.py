"""public_identity (issue #80 phase 4): the app-defined projection that is
the ONLY identity data serialized to the client.

Covers registration semantics (one projection per app, re-registration
replaces, reload-safe), the {"uid": ...} default when no projection is
registered, projection execution inside the request scope (including
identity_extras() access), and the page-path helper client_identity()
that opens its own scope around the walk.
"""
import pytest

from fymo.auth import Identity, identify, identity_extras, public_identity
from fymo.auth.context import (
    register_identity_extras_hook,
    reset_identity_extras_hooks,
)
from fymo.auth.identity import reset_identity_resolvers
from fymo.auth.public import (
    client_identity,
    project_identity,
    registered_public_identity,
    reset_public_identity,
)
from fymo.remote.context import request_scope
from fymo.remote.identity import set_secret


@pytest.fixture(autouse=True)
def _clean_registries():
    set_secret(b"test-secret-16-bytes-long")
    reset_identity_resolvers()
    reset_public_identity()
    reset_identity_extras_hooks()
    yield
    reset_identity_resolvers()
    reset_public_identity()
    reset_identity_extras_hooks()


def _register_header_resolver():
    @identify
    def by_header(event):
        uid = event.headers.get("x-user")
        return Identity(uid=uid) if uid else None
    return by_header


def _environ(user=None):
    env = {"REMOTE_ADDR": "127.0.0.1", "wsgi.url_scheme": "http"}
    if user is not None:
        env["HTTP_X_USER"] = user
    return env


# --------------- registration ---------------


def test_decorator_returns_fn_and_registers_it():
    @public_identity
    def project(ident):
        return {"uid": ident.uid, "plan": "pro"}

    assert registered_public_identity() is project


def test_reregistration_replaces_instead_of_erroring():
    @public_identity
    def project(ident):
        return {"uid": ident.uid, "v": 1}

    @public_identity
    def project2(ident):
        return {"uid": ident.uid, "v": 2}

    assert registered_public_identity() is project2
    _register_header_resolver()
    with request_scope(uid="u_anon", environ=_environ(user="alice")):
        assert project_identity() == {"uid": "alice", "v": 2}


def test_reset_drops_the_projection():
    @public_identity
    def project(ident):
        return {"uid": ident.uid}

    reset_public_identity()
    assert registered_public_identity() is None


# --------------- projection execution ---------------


def test_default_projection_is_uid_only():
    """With no projection registered a signed-in client sees exactly
    {"uid": ...}: safe (nothing crosses that was not whitelisted, the uid
    is already client-inferable) and still useful for the simple case."""
    _register_header_resolver()
    with request_scope(uid="u_anon", environ=_environ(user="u42")):
        assert project_identity() == {"uid": "u42"}


def test_anonymous_projects_to_none():
    _register_header_resolver()

    @public_identity
    def project(ident):
        return {"uid": ident.uid}

    with request_scope(uid="u_anon", environ=_environ()):
        assert project_identity() is None


def test_projection_receives_identity_and_output_is_plain_dict():
    _register_header_resolver()
    seen = {}

    @public_identity
    def project(ident):
        seen["ident"] = ident
        return {"uid": ident.uid, "name": "Alice"}

    with request_scope(uid="u_anon", environ=_environ(user="u1")):
        out = project_identity()
    assert seen["ident"] == Identity(uid="u1")
    assert out == {"uid": "u1", "name": "Alice"}
    assert type(out) is dict


def test_projection_may_read_identity_extras():
    _register_header_resolver()
    register_identity_extras_hook(lambda uid: {"email": f"{uid}@example.com"})

    @public_identity
    def project(ident):
        return {"uid": ident.uid, "name": identity_extras()["email"].split("@")[0]}

    with request_scope(uid="u_anon", environ=_environ(user="bob")):
        assert project_identity() == {"uid": "bob", "name": "bob"}


def test_non_mapping_projection_output_raises_typeerror():
    _register_header_resolver()

    @public_identity
    def project(ident):
        return ["not", "a", "mapping"]

    with request_scope(uid="u_anon", environ=_environ(user="u1")):
        with pytest.raises(TypeError, match="public_identity"):
            project_identity()


def test_project_identity_outside_scope_raises():
    _register_header_resolver()
    with pytest.raises(RuntimeError, match="request scope"):
        project_identity()


# --------------- client_identity (page-serving paths) ---------------


def test_client_identity_none_without_environ():
    _register_header_resolver()
    assert client_identity(None) is None


def test_client_identity_none_when_no_resolvers_registered():
    """Legacy apps (no @identify chain) never pay a scope or a resolver
    walk: the identity slot is simply null."""
    assert client_identity(_environ(user="u1")) is None


def test_client_identity_resolves_and_projects_inside_its_own_scope():
    _register_header_resolver()

    @public_identity
    def project(ident):
        return {"uid": ident.uid, "tier": "gold"}

    assert client_identity(_environ(user="u9")) == {"uid": "u9", "tier": "gold"}
    assert client_identity(_environ()) is None
