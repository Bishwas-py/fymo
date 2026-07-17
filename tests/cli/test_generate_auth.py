"""`fymo generate auth` (issue #80 phase 3): app-owned auth scaffolding.

The generator renders inert text templates into the target project.
Generated code imports only public fymo API (fymo.auth identity surface,
fymo.remote seams), never the legacy User/UserStore world, and the
password flow works end to end through the real remote router.
"""
import base64
import io
import json
import sqlite3
import sys
from pathlib import Path

import pytest

from fymo.auth import context as auth_context
from fymo.auth.discovery import import_auth_modules
from fymo.auth.identity import reset_identity_resolvers
from fymo.cli.commands.generate_auth import generate_auth
from fymo.remote import devalue, router as router_mod
from fymo.remote.context import request_scope
from fymo.remote.discovery import discover_remote_modules
from fymo.remote.identity import set_secret

PASSWORD_FILES = [
    "app/auth/__init__.py",
    "app/auth/resolver.py",
    "app/auth/store.py",
    "app/auth/extras.py",
    "app/auth/public.py",
    "app/remote/__init__.py",
    "app/remote/auth.py",
    "schema/users.sql",
]

FORBIDDEN_SNIPPETS = [
    "current_user",
    "UserStore",
    "fymo.auth.store",
    "fymo.auth.providers",
    "fymo.auth.context",
    "fymo.auth.session",
]


def _scaffold_project(tmp_path: Path) -> Path:
    (tmp_path / "fymo.yml").write_text("name: sample\nroutes:\n  root: home.index\n")
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "__init__.py").write_text('"""Application package"""')
    return tmp_path


def _generated_py_files(project: Path):
    yield from (project / "app" / "auth").glob("*.py")
    yield from (project / "app" / "remote").glob("*.py")


def _cleanup_app_modules() -> None:
    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]


@pytest.fixture(autouse=True)
def _clean():
    from fymo.auth.public import reset_public_identity

    set_secret(b"x" * 32)
    reset_identity_resolvers()
    reset_public_identity()
    auth_context.reset_identity_extras_hooks()
    _cleanup_app_modules()
    yield
    reset_identity_resolvers()
    reset_public_identity()
    auth_context.reset_identity_extras_hooks()
    _cleanup_app_modules()


# --------------- file sets ---------------


def test_password_variant_writes_expected_file_set(tmp_path, monkeypatch):
    project = _scaffold_project(tmp_path)
    monkeypatch.chdir(project)
    generate_auth("password")
    for rel in PASSWORD_FILES:
        assert (project / rel).is_file(), f"missing {rel}"


def test_clerk_variant_writes_resolver_only(tmp_path, monkeypatch):
    project = _scaffold_project(tmp_path)
    monkeypatch.chdir(project)
    generate_auth("clerk")
    assert (project / "app/auth/resolver.py").is_file()
    assert not (project / "app/auth/store.py").exists()
    assert not (project / "app/remote/auth.py").exists()
    assert not (project / "schema/users.sql").exists()


def test_skeleton_variant_writes_resolver_only(tmp_path, monkeypatch):
    project = _scaffold_project(tmp_path)
    monkeypatch.chdir(project)
    generate_auth("skeleton")
    assert (project / "app/auth/resolver.py").is_file()
    assert not (project / "app/auth/store.py").exists()
    assert not (project / "app/remote/auth.py").exists()


# --------------- refusals ---------------


def test_refuses_when_app_auth_exists(tmp_path, monkeypatch, capsys):
    project = _scaffold_project(tmp_path)
    (project / "app" / "auth").mkdir()
    monkeypatch.chdir(project)
    with pytest.raises(SystemExit):
        generate_auth("password")
    out = capsys.readouterr()
    combined = out.out + out.err
    assert "app/auth" in combined
    assert "delete or move" in combined.lower()


def test_refuses_when_app_remote_auth_exists(tmp_path, monkeypatch, capsys):
    project = _scaffold_project(tmp_path)
    (project / "app" / "remote").mkdir()
    (project / "app" / "remote" / "auth.py").write_text("def taken(): pass\n")
    monkeypatch.chdir(project)
    with pytest.raises(SystemExit):
        generate_auth("password")
    combined = "".join(capsys.readouterr())
    assert "app/remote/auth.py" in combined
    assert not (project / "app" / "auth").exists()


def test_existing_app_remote_dir_is_fine(tmp_path, monkeypatch):
    """Apps legitimately have app/remote/ already; only the auth.py file
    the generator wants to own may refuse."""
    project = _scaffold_project(tmp_path)
    (project / "app" / "remote").mkdir()
    (project / "app" / "remote" / "__init__.py").write_text("")
    (project / "app" / "remote" / "posts.py").write_text("def list() -> list: return []\n")
    monkeypatch.chdir(project)
    generate_auth("password")
    assert (project / "app/remote/auth.py").is_file()
    assert (project / "app/remote/posts.py").read_text() == "def list() -> list: return []\n"
    assert (project / "app/remote/__init__.py").read_text() == ""


def test_refuses_outside_a_fymo_project(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit):
        generate_auth("password")
    combined = "".join(capsys.readouterr())
    assert "fymo.yml" in combined


def test_refusal_leaves_no_partial_output(tmp_path, monkeypatch):
    project = _scaffold_project(tmp_path)
    (project / "app" / "auth").mkdir()
    monkeypatch.chdir(project)
    with pytest.raises(SystemExit):
        generate_auth("password")
    assert not (project / "schema").exists()


# --------------- generated code quality ---------------


def test_generated_python_compiles_all_variants(tmp_path, monkeypatch):
    for variant in ("password", "clerk", "skeleton"):
        (tmp_path / variant).mkdir()
        project = _scaffold_project(tmp_path / variant)
        monkeypatch.chdir(project)
        generate_auth(variant)
        for py in _generated_py_files(project):
            compile(py.read_text(), str(py), "exec")


def test_generated_code_never_imports_legacy_auth(tmp_path, monkeypatch):
    for variant in ("password", "clerk", "skeleton"):
        (tmp_path / variant).mkdir()
        project = _scaffold_project(tmp_path / variant)
        monkeypatch.chdir(project)
        generate_auth(variant)
        for py in _generated_py_files(project):
            text = py.read_text()
            for snippet in FORBIDDEN_SNIPPETS:
                assert snippet not in text, f"{py.name} ({variant}) references {snippet}"


def test_clerk_resolver_compiles_without_pyjwt(tmp_path, monkeypatch):
    """The clerk template imports pyjwt lazily, inside the verifier, so the
    module compiles and imports in an app that has not yet added
    pyjwt[crypto] to its dependencies. Compile-only check: never imports jwt."""
    project = _scaffold_project(tmp_path)
    monkeypatch.chdir(project)
    generate_auth("clerk")
    text = (project / "app/auth/resolver.py").read_text()
    compile(text, "resolver.py", "exec")
    assert "pyjwt[crypto]" in text
    header = text[:800]
    assert "dependencies" in header


def test_next_steps_printed(tmp_path, monkeypatch, capsys):
    project = _scaffold_project(tmp_path)
    monkeypatch.chdir(project)
    generate_auth("password")
    out = capsys.readouterr().out
    assert "signin" in out
    assert "require_auth" in out
    assert "schema/users.sql" in out
    # The endpoints land in app/remote/auth.py directly, so no manual
    # wrap-or-move step may be suggested anymore.
    assert "wrap or move" not in out


# --------------- click surface ---------------


def test_cli_generate_auth_variants(tmp_path):
    from click.testing import CliRunner
    from fymo.cli.main import cli

    runner = CliRunner()
    for args, marker in (
        (["generate", "auth"], "app/remote/auth.py"),
        (["generate", "auth", "--clerk"], "pyjwt"),
        (["generate", "auth", "--skeleton"], "resolver"),
    ):
        with runner.isolated_filesystem(temp_dir=tmp_path):
            _scaffold_project(Path.cwd())
            result = runner.invoke(cli, args)
            assert result.exit_code == 0, result.output
            assert marker in result.output or (Path.cwd() / "app/auth/resolver.py").is_file()
            assert (Path.cwd() / "app/auth/resolver.py").is_file()


def test_cli_clerk_and_skeleton_are_mutually_exclusive(tmp_path):
    from click.testing import CliRunner
    from fymo.cli.main import cli

    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        _scaffold_project(Path.cwd())
        result = runner.invoke(cli, ["generate", "auth", "--clerk", "--skeleton"])
        assert result.exit_code != 0
        assert "mutually exclusive" in result.output
        assert not (Path.cwd() / "app" / "auth").exists()


# --------------- runtime behavior ---------------


def test_skeleton_resolver_registers_and_returns_none(tmp_path, monkeypatch):
    from fymo.auth.identity import current_uid, registered_identity_resolvers

    project = _scaffold_project(tmp_path)
    monkeypatch.chdir(project)
    generate_auth("skeleton")
    assert import_auth_modules(project) == ["app.auth.resolver"]
    assert len(registered_identity_resolvers()) == 1
    with request_scope(uid="u_anon", environ={"HTTP_COOKIE": "session=whatever"}):
        assert current_uid() is None


def test_password_resolver_round_trips_signed_token(tmp_path, monkeypatch):
    from fymo.auth import sign_token
    from fymo.auth.identity import current_uid

    project = _scaffold_project(tmp_path)
    monkeypatch.chdir(project)
    generate_auth("password")
    import_auth_modules(project)
    token = sign_token("42")
    with request_scope(uid="u_anon", environ={"HTTP_COOKIE": f"session={token}"}):
        assert current_uid() == "42"
    with request_scope(uid="u_anon", environ={"HTTP_COOKIE": "session=tampered"}):
        assert current_uid() is None


def test_password_public_projection_whitelists_uid_and_name(tmp_path, monkeypatch):
    """The generated app/auth/public.py registers a public_identity
    projection that exposes only {uid, name-derived-from-email}: the email
    address itself (PII) and the rest of the extras stay server-side."""
    from fymo.auth import sign_token
    from fymo.auth.public import project_identity, registered_public_identity

    project = _scaffold_project(tmp_path)
    monkeypatch.chdir(project)
    generate_auth("password")
    modules = import_auth_modules(project)
    assert "app.auth.public" in modules
    assert registered_public_identity() is not None

    monkeypatch.syspath_prepend(str(project))
    from app.auth import store
    uid = store.create("carol@example.com", "hunter2hunter2")
    token = sign_token(uid)
    with request_scope(uid="u_anon", environ={"HTTP_COOKIE": f"session={token}"}):
        projected = project_identity()
    assert projected == {"uid": uid, "name": "carol"}
    assert "email" not in projected


# --------------- password flow end to end via the remote router ---------------


def _b64url(s: str) -> str:
    return base64.urlsafe_b64encode(s.encode("utf-8")).rstrip(b"=").decode("ascii")


# The discovered content hash of app/remote/auth.py, set by generated_app.
# Requests hit /_fymo/remote/<this hash>/<fn>, same URL shape the browser
# client uses.
_auth_module_hash = None


def _call(fn: str, args: list, cookies: str = ""):
    body = json.dumps({"payload": _b64url(devalue.stringify(args))}).encode()
    env = {
        "REQUEST_METHOD": "POST",
        "PATH_INFO": f"/_fymo/remote/{_auth_module_hash}/{fn}",
        "CONTENT_LENGTH": str(len(body)),
        "CONTENT_TYPE": "application/json",
        "HTTP_COOKIE": cookies,
        "HTTP_HOST": "x",
        "HTTP_ORIGIN": "http://x",
        "wsgi.url_scheme": "http",
        "REMOTE_ADDR": "127.0.0.1",
        "wsgi.input": io.BytesIO(body),
        "wsgi.errors": sys.stderr,
    }
    responses = []

    def sr(status, headers):
        responses.append((status, headers))

    out = b"".join(router_mod.handle_remote(env, sr))
    return responses[0], json.loads(out)


def _session_cookie(headers) -> "str | None":
    for k, v in headers:
        if k.lower() == "set-cookie" and v.startswith("session="):
            return v.split(";", 1)[0]
    return None


@pytest.fixture
def generated_app(tmp_path, monkeypatch):
    """Scaffold a project, generate password auth, and reach the endpoints
    through the real pipeline: import_auth_modules registers the resolver,
    discover_remote_modules scans app/remote/*.py exactly as the build
    does, and the router imports app.remote.auth itself per request. The
    only harness stitch is _resolve_module_for_hash, wired to the
    discovered hash->module map, standing in for the production
    ManifestCache.module_for_hash lookup that dev/prod servers install.
    Nothing injects the functions: if discovery could not see them, every
    call here would 404."""
    project = _scaffold_project(tmp_path)
    monkeypatch.chdir(project)
    generate_auth("password")
    import_auth_modules(project)
    monkeypatch.syspath_prepend(str(project))
    discovered = discover_remote_modules(project)
    assert set(discovered.get("auth", {})) == {"signup", "login", "logout", "me"}
    hash_to_module = {
        next(iter(fns.values())).module_hash: module
        for module, fns in discovered.items()
    }
    monkeypatch.setattr(router_mod, "_resolve_module_for_hash", hash_to_module.get)
    global _auth_module_hash
    _auth_module_hash = next(iter(discovered["auth"].values())).module_hash
    return project


def test_signup_sets_session_cookie_and_uid_resolves(generated_app):
    from fymo.auth.identity import current_uid

    (status, headers), env = _call("signup", ["alice@example.com", "longpassword"])
    assert status.startswith("200"), env
    assert env["type"] == "result", env
    result = devalue.parse(env["result"])
    assert result["email"] == "alice@example.com"
    cookie = _session_cookie(headers)
    assert cookie is not None
    with request_scope(uid="u_anon", environ={"HTTP_COOKIE": cookie}):
        assert current_uid() == result["uid"]


def test_signup_duplicate_email_conflicts(generated_app):
    _call("signup", ["dup@example.com", "longpassword"])
    (_, _), env = _call("signup", ["dup@example.com", "otherlongpassword"])
    assert env["type"] == "error"
    assert env["status"] == 409


def test_login_wrong_password_is_401(generated_app):
    _call("signup", ["bob@example.com", "longpassword"])
    (_, _), env = _call("login", ["bob@example.com", "wrongpassword"])
    assert env["type"] == "error"
    assert env["status"] == 401


def test_login_unknown_email_same_error_as_wrong_password(generated_app):
    (_, _), env = _call("login", ["ghost@example.com", "longpassword"])
    assert env["type"] == "error"
    assert env["status"] == 401


def test_login_redirects_and_sets_cookie(generated_app):
    _call("signup", ["carol@example.com", "longpassword"])
    (status, headers), env = _call("login", ["carol@example.com", "longpassword", "/dashboard"])
    assert env["type"] == "redirect", env
    assert env["location"] == "/dashboard"
    assert _session_cookie(headers) is not None


def test_login_open_redirect_guard(generated_app):
    """Browsers normalize backslashes to slashes in http(s) URLs, so
    "/\\evil.example" becomes the protocol-relative "//evil.example" after
    the redirect: backslash anywhere in `next` must fall back to "/".
    A leading space fails the startswith("/") check, pinned here so the
    whitespace vector stays covered if the guard is ever rewritten."""
    _call("signup", ["dave@example.com", "longpassword"])
    evil_nexts = (
        "//evil.example",
        "https://evil.example",
        "javascript:alert(1)",
        "/\\evil.example",
        "/\\/evil.example",
        " //evil.example",
    )
    for evil in evil_nexts:
        (_, _), env = _call("login", ["dave@example.com", "longpassword", evil])
        assert env["type"] == "redirect"
        assert env["location"] == "/", f"unsafe next {evil!r} leaked through"


def test_password_over_max_length_is_rejected(generated_app):
    """scrypt cost grows with input size; the router's 1 MiB body cap alone
    still allows CPU-amplifying passwords, so _validate caps them at 1024."""
    (_, _), env = _call("signup", ["hank@example.com", "x" * 1025])
    assert env["type"] == "error"
    assert env["status"] == 400

    (_, _), env = _call("login", ["hank@example.com", "x" * 1025])
    assert env["type"] == "error"
    assert env["status"] == 400

    (_, _), env = _call("signup", ["hank@example.com", "x" * 1024])
    assert env["type"] == "result"


def test_me_round_trip_and_logout(generated_app):
    (_, headers), env = _call("signup", ["erin@example.com", "longpassword"])
    cookie = _session_cookie(headers)

    (_, _), env = _call("me", [], cookies=cookie)
    me = devalue.parse(env["result"])
    assert me["email"] == "erin@example.com"

    (_, headers), env = _call("logout", [], cookies=cookie)
    assert devalue.parse(env["result"]) == {"ok": True}
    cleared = _session_cookie(headers)
    assert cleared == "session="

    (_, _), env = _call("me", [])
    assert devalue.parse(env["result"]) is None


def test_typed_extras_replace_current_user_dot_email(generated_app):
    """The typed-accessor regression: current_user().email must have a typed
    replacement. current_extras() returns a frozen dataclass loaded from the
    app's own users table via the extras hook."""
    import dataclasses
    import importlib

    (_, headers), _ = _call("signup", ["frank@example.com", "longpassword"])
    cookie = _session_cookie(headers)

    extras_mod = sys.modules["app.auth.extras"]
    with request_scope(uid="u_anon", environ={"HTTP_COOKIE": cookie}):
        extras = extras_mod.current_extras()
        assert extras is not None
        assert extras.email == "frank@example.com"
        assert dataclasses.is_dataclass(extras)
        with pytest.raises(dataclasses.FrozenInstanceError):
            extras.email = "other@example.com"
    with request_scope(uid="u_anon", environ={}):
        assert extras_mod.current_extras() is None


def test_users_table_matches_generated_schema(generated_app):
    _call("signup", ["gina@example.com", "longpassword"])
    db = generated_app / "data" / "app.db"
    assert db.is_file()
    conn = sqlite3.connect(db)
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(users)")}
    finally:
        conn.close()
    assert cols == {"id", "email", "password_hash", "created_at"}
