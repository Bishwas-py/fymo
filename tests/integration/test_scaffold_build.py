"""Issue #77 acceptance, end to end on a real `fymo new` scaffold.

The scaffolded root layout imports app/assets/app.css; this suite adds a
real @font-face (real woff2 bytes in app/assets/fonts/) and a section
layout with its own stylesheet, then proves the whole story on both build
paths:

- prod (`fymo build` / BuildPipeline): the font is content-hashed into
  dist/client, the css url() is rewritten to a /dist/client/ path that the
  running app actually serves, and pages link their layout chain's CSS
  root-first -- section css only on pages under that section.
- dev (DevOrchestrator / dev.mjs): same loader + css pipeline, watched.

node_modules is symlinked from examples/blog_app (the scaffold's
package.json pins the same toolchain), per the convention in
tests/integration/test_fresh_install_smoke.py.
"""
import io
import shutil
import sys
import time
from pathlib import Path

import pytest

from fymo.build.manifest import Manifest
from fymo.build.pipeline import BuildPipeline
from fymo.cli.commands.new import create_project
from tests.conftest import BLOG_APP

WOFF2_BYTES = b"wOF2\x00\x01\x00\x00" + bytes(range(256))

SECTION_LAYOUT = """<script>
  import '../../assets/admin.css';

  let { children } = $props();
</script>

<div class="admin-shell">{@render children()}</div>
"""

SECTION_PAGE = """<script>
  let { title } = $props();
</script>

<h1>{title}</h1>
"""


@pytest.fixture(scope="module")
def scaffold(tmp_path_factory, node_available) -> Path:
    nm = BLOG_APP / "node_modules"
    if not nm.is_dir():
        pytest.skip("examples/blog_app/node_modules not found — run npm install in examples/blog_app/")

    workdir = tmp_path_factory.mktemp("scaffold")
    import os
    old_cwd = os.getcwd()
    os.chdir(workdir)
    try:
        create_project("fontapp")
    finally:
        os.chdir(old_cwd)
    project = workdir / "fontapp"
    (project / "node_modules").symlink_to(nm)

    # Real font wired into the scaffolded app.css.
    (project / "app" / "assets" / "fonts" / "inter.woff2").write_bytes(WOFF2_BYTES)
    app_css = project / "app" / "assets" / "app.css"
    app_css.write_text(
        "@font-face { font-family: 'Inter'; src: url('./fonts/inter.woff2') format('woff2'); }\n"
        + app_css.read_text()
    )

    # A section with its own layout + stylesheet: only pages under it may
    # carry admin.css.
    (project / "app" / "assets" / "admin.css").write_text(".admin-shell { padding: 1px; }\n")
    admin_dir = project / "app" / "templates" / "admin"
    admin_dir.mkdir()
    (admin_dir / "_layout.svelte").write_text(SECTION_LAYOUT)
    (admin_dir / "index.svelte").write_text(SECTION_PAGE)
    (project / "app" / "controllers" / "admin.py").write_text(
        "context = {'title': 'Admin'}\n"
    )
    fymo_yml = project / "fymo.yml"
    fymo_yml.write_text(fymo_yml.read_text().replace("- posts", "- admin"))
    return project


@pytest.fixture(scope="module")
def prod_built(scaffold: Path) -> Manifest:
    result = BuildPipeline(scaffold).build(dev=False)
    return Manifest.read(result.manifest_path)


def _get(app, path):
    responses = []

    def start_response(status, headers):
        responses.append((status, headers))

    environ = {
        "REQUEST_METHOD": "GET",
        "PATH_INFO": path,
        "QUERY_STRING": "",
        "SERVER_NAME": "localhost", "SERVER_PORT": "8000", "SERVER_PROTOCOL": "HTTP/1.1",
        "wsgi.input": io.BytesIO(), "wsgi.errors": sys.stderr, "wsgi.url_scheme": "http",
    }
    body = b"".join(app(environ, start_response))
    status, headers = responses[0]
    return status, dict(headers), body


def _font_url_from(css_text: str) -> str:
    import re
    m = re.search(r"url\(\"?(/dist/client/inter\.[A-Z0-9]+\.woff2)\"?\)", css_text)
    assert m, f"font url not rewritten to /dist/client/: {css_text}"
    return m.group(1)


def test_prod_build_hashes_font_and_rewrites_css_url(scaffold: Path, prod_built: Manifest):
    root_css = prod_built.layouts["_root"].css
    assert root_css is not None
    css_text = (scaffold / "dist" / root_css).read_text()
    font_url = _font_url_from(css_text)
    hashed = scaffold / "dist" / font_url[len("/dist/"):]
    assert hashed.is_file()
    assert hashed.read_bytes() == WOFF2_BYTES


def test_prod_pages_link_layout_chain_css_root_first(scaffold: Path, prod_built: Manifest):
    from fymo import create_app
    app = create_app(scaffold, dev=False)
    try:
        root_css = prod_built.layouts["_root"].css
        admin_css = prod_built.layouts["admin"].css
        assert admin_css is not None

        status, _, body = _get(app, "/admin")
        assert status == "200 OK"
        html = body.decode("utf-8")
        root_idx = html.index(f'<link rel="stylesheet" href="/dist/{root_css}">')
        admin_idx = html.index(f'<link rel="stylesheet" href="/dist/{admin_css}">')
        assert root_idx < admin_idx

        status, _, body = _get(app, "/")
        assert status == "200 OK"
        html = body.decode("utf-8")
        assert f'<link rel="stylesheet" href="/dist/{root_css}">' in html
        assert admin_css not in html

        # The rewritten font URL actually serves through the running app.
        css_text = (scaffold / "dist" / root_css).read_text()
        font_url = _font_url_from(css_text)
        status, headers, body = _get(app, font_url)
        assert status == "200 OK"
        assert headers["Content-Type"] == "font/woff2"
        assert body == WOFF2_BYTES
    finally:
        app.shutdown()


def test_dev_build_path_produces_same_asset_pipeline(scaffold: Path, prod_built: Manifest):
    """dev.mjs (watch mode) must run the same loader/publicPath/css pipeline
    as build.mjs. Runs after the prod tests so wiping dist/ can't starve
    them, and asserts on the freshly dev-written manifest."""
    from fymo.build.dev_orchestrator import DevOrchestrator

    shutil.rmtree(scaffold / "dist")
    orch = DevOrchestrator(project_root=scaffold)
    orch.start()
    try:
        deadline = time.time() + 20
        while time.time() < deadline:
            if (scaffold / "dist" / "manifest.json").exists():
                break
            time.sleep(0.1)
        else:
            pytest.fail("dev manifest never written")
        manifest = Manifest.read(scaffold / "dist" / "manifest.json")
        root_css = manifest.layouts["_root"].css
        assert root_css is not None
        css_text = (scaffold / "dist" / root_css).read_text()
        font_url = _font_url_from(css_text)
        hashed = scaffold / "dist" / font_url[len("/dist/"):]
        assert hashed.is_file()
        assert hashed.read_bytes() == WOFF2_BYTES
        assert manifest.layouts["admin"].css is not None
    finally:
        orch.stop()
