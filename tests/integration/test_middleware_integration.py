"""Middleware applied through a real FymoApp: rate limit, body cap, security headers."""
import io
import sys
from pathlib import Path
import pytest


def _wsgi(app, path: str, method: str = "GET", body: bytes = b"",
          remote_addr: str = "127.0.0.1", scheme: str = "http",
          forwarded_proto: str | None = None):
    responses = []
    def sr(status, headers): responses.append((status, headers))
    environ = {
        "REQUEST_METHOD": method, "PATH_INFO": path, "QUERY_STRING": "",
        "CONTENT_LENGTH": str(len(body)), "CONTENT_TYPE": "application/octet-stream",
        "HTTP_COOKIE": "",
        "SERVER_NAME": "x", "SERVER_PORT": "0", "SERVER_PROTOCOL": "HTTP/1.1",
        "REMOTE_ADDR": remote_addr,
        "wsgi.input": io.BytesIO(body), "wsgi.errors": sys.stderr,
        "wsgi.url_scheme": scheme,
    }
    if forwarded_proto is not None:
        environ["HTTP_X_FORWARDED_PROTO"] = forwarded_proto
    out = b"".join(app(environ, sr))
    return responses[0], out


@pytest.mark.usefixtures("node_available")
def test_middleware_injects_security_headers_into_responses(example_app: Path, monkeypatch):
    from fymo.build.pipeline import BuildPipeline
    BuildPipeline(project_root=example_app).build(dev=False)
    monkeypatch.chdir(example_app)
    from fymo import create_app
    app = create_app(example_app)
    try:
        (status, headers), _ = _wsgi(app, "/dist/manifest.json")
        keys = {k.lower() for k, _ in headers}
        assert "x-content-type-options" in keys
        assert "x-frame-options" in keys
        assert "referrer-policy" in keys
        assert "permissions-policy" in keys
        # HSTS absent over plain http
        assert "strict-transport-security" not in keys
    finally:
        if app.sidecar:
            app.sidecar.stop()


@pytest.mark.usefixtures("node_available")
def test_middleware_adds_hsts_over_https(example_app: Path, monkeypatch):
    from fymo.build.pipeline import BuildPipeline
    BuildPipeline(project_root=example_app).build(dev=False)
    monkeypatch.chdir(example_app)
    from fymo import create_app
    app = create_app(example_app)
    try:
        (status, headers), _ = _wsgi(app, "/dist/manifest.json", scheme="https")
        keys = {k.lower() for k, _ in headers}
        assert "strict-transport-security" in keys
    finally:
        if app.sidecar:
            app.sidecar.stop()


@pytest.mark.usefixtures("node_available")
def test_middleware_adds_default_csp_report_only_in_prod(example_app: Path, monkeypatch):
    """A default `security.headers.extra` CSP is not configured, so fymo
    injects its own report-only baseline in production."""
    from fymo.build.pipeline import BuildPipeline
    BuildPipeline(project_root=example_app).build(dev=False)
    monkeypatch.chdir(example_app)
    from fymo import create_app
    app = create_app(example_app, dev=False)
    try:
        (status, headers), _ = _wsgi(app, "/dist/manifest.json")
        header_dict = {k.lower(): v for k, v in headers}
        assert "content-security-policy-report-only" in header_dict
        assert "default-src 'self'" in header_dict["content-security-policy-report-only"]
        assert "content-security-policy" not in header_dict
    finally:
        if app.sidecar:
            app.sidecar.stop()


@pytest.mark.usefixtures("node_available")
def test_middleware_no_default_csp_or_hsts_in_dev(example_app: Path, monkeypatch):
    from fymo.build.pipeline import BuildPipeline
    BuildPipeline(project_root=example_app).build(dev=True)
    monkeypatch.chdir(example_app)
    from fymo import create_app
    app = create_app(example_app, dev=True)
    try:
        (status, headers), _ = _wsgi(app, "/dist/manifest.json", scheme="https")
        keys = {k.lower() for k, _ in headers}
        assert "content-security-policy-report-only" not in keys
        assert "content-security-policy" not in keys
        assert "strict-transport-security" not in keys
    finally:
        if app.sidecar:
            app.sidecar.stop()


@pytest.mark.usefixtures("node_available")
def test_middleware_hsts_over_resolved_scheme_behind_trusted_proxy(example_app: Path, monkeypatch):
    """Behind a TLS-terminating proxy the app sees http, but with
    `trust_proxy: true` and a forwarded https scheme, HSTS still fires."""
    fymo_yml = example_app / "fymo.yml"
    text = fymo_yml.read_text()
    fymo_yml.write_text(text + "\nlimits:\n  rate_limit:\n    trust_proxy: true\n")

    from fymo.build.pipeline import BuildPipeline
    BuildPipeline(project_root=example_app).build(dev=False)
    monkeypatch.chdir(example_app)
    from fymo import create_app
    app = create_app(example_app, dev=False)
    try:
        (status, headers), _ = _wsgi(
            app, "/dist/manifest.json", scheme="http", forwarded_proto="https",
        )
        keys = {k.lower() for k, _ in headers}
        assert "strict-transport-security" in keys
    finally:
        if app.sidecar:
            app.sidecar.stop()


@pytest.mark.usefixtures("node_available")
def test_middleware_hsts_anti_spoof_without_trust_proxy(example_app: Path, monkeypatch):
    """A client-supplied X-Forwarded-Proto: https must NOT force HSTS on
    when the deployment hasn't opted into trusting a reverse proxy —
    trust_proxy defaults to false."""
    from fymo.build.pipeline import BuildPipeline
    BuildPipeline(project_root=example_app).build(dev=False)
    monkeypatch.chdir(example_app)
    from fymo import create_app
    app = create_app(example_app, dev=False)
    try:
        (status, headers), _ = _wsgi(
            app, "/dist/manifest.json", scheme="http", forwarded_proto="https",
        )
        keys = {k.lower() for k, _ in headers}
        assert "strict-transport-security" not in keys
    finally:
        if app.sidecar:
            app.sidecar.stop()


@pytest.mark.usefixtures("node_available")
def test_body_limit_rejects_oversized(example_app: Path, monkeypatch):
    """Override the default cap to a tiny value and verify the 413 path."""
    fymo_yml = example_app / "fymo.yml"
    text = fymo_yml.read_text()
    fymo_yml.write_text(text + "\nlimits:\n  max_body_bytes: 10\n")

    from fymo.build.pipeline import BuildPipeline
    BuildPipeline(project_root=example_app).build(dev=False)
    monkeypatch.chdir(example_app)
    from fymo import create_app
    app = create_app(example_app)
    try:
        big = b"x" * 100
        (status, _), body = _wsgi(app, "/_fymo/remote/abc/hello", method="POST", body=big)
        assert status.startswith("413"), status
        assert b"Payload Too Large" in body
    finally:
        if app.sidecar:
            app.sidecar.stop()


@pytest.mark.usefixtures("node_available")
def test_rate_limit_blocks_after_capacity(example_app: Path, monkeypatch):
    """Tight rpm cap on a path prefix, verify 429 with Retry-After + X-RateLimit-Limit."""
    fymo_yml = example_app / "fymo.yml"
    text = fymo_yml.read_text()
    fymo_yml.write_text(text + (
        "\nlimits:\n"
        "  rate_limit:\n"
        "    requests_per_minute: 2\n"
        "    paths:\n"
        "      \"/dist/\": 2\n"
    ))

    from fymo.build.pipeline import BuildPipeline
    BuildPipeline(project_root=example_app).build(dev=False)
    monkeypatch.chdir(example_app)
    from fymo import create_app
    app = create_app(example_app)
    try:
        # First two requests pass
        for _ in range(2):
            (status, _), _ = _wsgi(app, "/dist/manifest.json")
            assert status.startswith("200"), status
        # Third request from the same IP gets 429
        (status, headers), body = _wsgi(app, "/dist/manifest.json")
        assert status.startswith("429"), status
        header_dict = {k.lower(): v for k, v in headers}
        assert header_dict["retry-after"]
        assert header_dict["x-ratelimit-limit"] == "2"
        assert header_dict["x-ratelimit-remaining"] == "0"
        assert b"Too Many Requests" in body
        # Different IP still has its own bucket
        (status, _), _ = _wsgi(app, "/dist/manifest.json", remote_addr="9.9.9.9")
        assert status.startswith("200")
    finally:
        if app.sidecar:
            app.sidecar.stop()
