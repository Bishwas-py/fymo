"""FymoApp boot-time behavior for auth providers that need an optional
extra (issue #59). `type: clerk` in fymo.yml must fail construction outright,
naming the exact `pip install` command, when pyjwt[crypto] isn't installed --
the same "refuse to start" shape as `fymo serve --prod --server granian`
when granian is missing (fymo/cli/commands/serve.py:_resolve_prod_server).
Silently booting with auth half-wired (or worse, disabled) is explicitly the
failure mode this guards against.
"""
from pathlib import Path

import pytest

from fymo.core.server import FymoApp


def _write_fake_sidecar(tmp_path: Path) -> None:
    """FymoApp always requires dist/sidecar.mjs (no dev-mode bypass). Same
    minimal length-prefixed-JSON-IPC stub used by test_dotenv_loading.py /
    test_logging.py -- only needed by the "boots successfully" test below,
    which must get all the way through __init__; the "fails at boot" test
    never reaches the dist/ check at all, since provider construction now
    raises earlier in __init__ (inside _init_auth)."""
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    (dist_dir / "sidecar.mjs").write_text(
        "let buf = Buffer.alloc(0);\n"
        "process.stdin.on('data', (chunk) => {\n"
        "  buf = Buffer.concat([buf, chunk]);\n"
        "  while (buf.length >= 4) {\n"
        "    const len = buf.readUInt32BE(0);\n"
        "    if (buf.length < 4 + len) break;\n"
        "    const msg = JSON.parse(buf.slice(4, 4 + len).toString('utf8'));\n"
        "    buf = buf.slice(4 + len);\n"
        "    const replyBody = Buffer.from(JSON.stringify({ ok: true, id: msg.id }), 'utf8');\n"
        "    const header = Buffer.alloc(4);\n"
        "    header.writeUInt32BE(replyBody.length, 0);\n"
        "    process.stdout.write(Buffer.concat([header, replyBody]));\n"
        "  }\n"
        "});\n"
    )


def _write_clerk_fymo_yml(tmp_path: Path) -> None:
    (tmp_path / "fymo.yml").write_text(
        "name: ClerkBootTest\n"
        "routes: {}\n"
        "auth:\n"
        "  enabled: true\n"
        "  providers:\n"
        "    - type: clerk\n"
    )


def test_fymo_app_refuses_to_start_when_clerk_configured_without_pyjwt(tmp_path, monkeypatch):
    monkeypatch.setenv("FYMO_SECRET", "x" * 32)
    monkeypatch.setenv("CLERK_ISSUER", "https://x.clerk.accounts.dev")
    monkeypatch.setattr("fymo.auth.providers.clerk._pyjwt_available", lambda: False)
    _write_clerk_fymo_yml(tmp_path)

    with pytest.raises(RuntimeError, match=r"pip install 'fymo\[clerk\]'"):
        FymoApp(project_root=tmp_path, dev=True)


def test_fymo_app_boots_when_clerk_configured_and_pyjwt_available(tmp_path, monkeypatch):
    """The extra's deps actually present (this dev environment has
    pyjwt[crypto] as a real dev dependency) must restore today's behavior:
    the app boots, auth is enabled, and a ClerkProvider is installed."""
    pytest.importorskip("jwt")
    pytest.importorskip("cryptography")
    monkeypatch.setenv("FYMO_SECRET", "x" * 32)
    monkeypatch.setenv("CLERK_ISSUER", "https://x.clerk.accounts.dev")
    _write_clerk_fymo_yml(tmp_path)
    _write_fake_sidecar(tmp_path)

    app = FymoApp(project_root=tmp_path, dev=True)
    try:
        assert app.auth_enabled is True
        from fymo.auth.providers.clerk import ClerkProvider
        assert any(isinstance(p, ClerkProvider) for p in app.auth_providers)
    finally:
        app.shutdown()


@pytest.mark.usefixtures("node_available")
def test_fymo_app_boots_password_only_with_zero_auth_extras(tmp_path, monkeypatch):
    """Acceptance criterion: a fresh install plus the password provider must
    still boot and enable auth with zero optional extras installed. Doesn't
    uninstall anything from the shared venv (that would be fragile and leak
    across the rest of the suite) -- it proves the same thing by asserting
    jwt/cryptography are never imported to get here, mirroring how the
    clerk-missing test above simulates absence via monkeypatch instead of
    physically removing a package."""
    import sys
    for name in ("jwt", "cryptography"):
        sys.modules.pop(name, None)

    monkeypatch.setenv("FYMO_SECRET", "x" * 32)
    (tmp_path / "fymo.yml").write_text(
        "name: PasswordBootTest\n"
        "routes: {}\n"
        "auth:\n"
        "  enabled: true\n"
    )
    _write_fake_sidecar(tmp_path)

    app = FymoApp(project_root=tmp_path, dev=True)
    try:
        assert app.auth_enabled is True
        from fymo.auth.providers.password import PasswordProvider
        assert len(app.auth_providers) == 1
        assert isinstance(app.auth_providers[0], PasswordProvider)
    finally:
        app.shutdown()

    assert "jwt" not in sys.modules
    assert "cryptography" not in sys.modules
