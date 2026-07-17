"""SSR-time identity: current_uid() must resolve during page render, from a
copy of blog_app (which ships an app/auth/ session resolver) with one extra
route added: `whoami`, whose controller reads the identity and puts the
email from identity_extras() in props, and whose template renders it. This
proves the "logged-out flash" is gone: the session is visible at render
time, not just after the client hydrates and makes its own remote call.
"""
import io
import sys
from pathlib import Path

import pytest

_WHOAMI_CONTROLLER = '''"""Whoami controller: exercises current_uid() during SSR."""
from fymo.auth import current_uid, identity_extras


def getContext():
    uid = current_uid()
    return {"email": identity_extras().get("email") if uid else None}
'''

_WHOAMI_TEMPLATE = """<script>
  let { email } = $props();
</script>

<div>
  {#if email}
    <p data-testid="whoami">Logged in as {email}</p>
  {:else}
    <p data-testid="whoami">Not logged in</p>
  {/if}
</div>
"""


@pytest.fixture
def whoami_app(blog_app: Path) -> Path:
    """Layer an extra `whoami` controller + template onto the shared
    blog_app fixture, rather than forking its own copy-into-tmpdir logic.
    blog_app already handles the copytree, node_modules symlink, and
    sys.path/sys.modules hygiene -- this only adds the route on top."""
    dest = blog_app

    (dest / "app" / "controllers" / "whoami.py").write_text(_WHOAMI_CONTROLLER)
    tpl_dir = dest / "app" / "templates" / "whoami"
    tpl_dir.mkdir(parents=True)
    (tpl_dir / "index.svelte").write_text(_WHOAMI_TEMPLATE)

    fymo_yml = dest / "fymo.yml"
    text = fymo_yml.read_text()
    assert "    - tags\n" in text, "unexpected fymo.yml shape in examples/blog_app"
    text = text.replace("    - tags\n", "    - tags\n    - whoami\n")
    fymo_yml.write_text(text)

    return dest


def _wsgi_get(app, path: str, *, cookies: str = ""):
    responses = []

    def sr(status, headers):
        responses.append((status, headers))

    out = b"".join(app({
        "REQUEST_METHOD": "GET",
        "PATH_INFO": path,
        "QUERY_STRING": "",
        "CONTENT_LENGTH": "0",
        "CONTENT_TYPE": "text/plain",
        "HTTP_COOKIE": cookies,
        "SERVER_NAME": "x", "SERVER_PORT": "0", "SERVER_PROTOCOL": "HTTP/1.1",
        "REMOTE_ADDR": "127.0.0.1",
        "wsgi.input": io.BytesIO(b""), "wsgi.errors": sys.stderr,
        "wsgi.url_scheme": "http",
    }, sr))
    return responses[0], out


@pytest.mark.usefixtures("node_available")
def test_ssr_sees_logged_in_user_from_session_cookie(whoami_app: Path):
    from fymo.build.pipeline import BuildPipeline
    BuildPipeline(project_root=whoami_app).build(dev=False)

    from fymo import create_app
    from fymo.auth import sign_token

    app = create_app(whoami_app)
    try:
        from app.auth import store
        uid = store.create("alex@example.com", "longpassword")
        token = sign_token(uid)

        (status, _), html = _wsgi_get(app, "/whoami", cookies=f"session={token}")
        assert status.startswith("200"), (status, html)
        assert b"Logged in as alex@example.com" in html
    finally:
        if app.sidecar:
            app.sidecar.stop()


@pytest.mark.usefixtures("node_available")
def test_ssr_logged_out_has_no_user_and_does_not_crash(whoami_app: Path):
    from fymo.build.pipeline import BuildPipeline
    BuildPipeline(project_root=whoami_app).build(dev=False)

    from fymo import create_app

    app = create_app(whoami_app)
    try:
        (status, _), html = _wsgi_get(app, "/whoami")
        assert status.startswith("200"), (status, html)
        assert b"Not logged in" in html
    finally:
        if app.sidecar:
            app.sidecar.stop()
