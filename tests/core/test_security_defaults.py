"""Production-default CSP + proxy-aware HSTS — unit tests.

Covers task B6: fymo ships a sensible default Content-Security-Policy in
production (report-only, so it can never break an app out of the box) and
makes HSTS fire over the *resolved* scheme so it still works behind a
TLS-terminating reverse proxy — without trusting a spoofable
X-Forwarded-Proto header unless trust_proxy is explicitly on.
"""
from fymo.core.middleware import (
    DEFAULT_CSP_REPORT_ONLY,
    MiddlewareSettings,
    security_headers_for,
    wrap_start_response,
)


def _https_via_proxy(xfp: str = "https") -> dict:
    return {"wsgi.url_scheme": "http", "HTTP_X_FORWARDED_PROTO": xfp}


# ---------------- Default CSP ----------------


def test_prod_default_includes_report_only_csp():
    headers = security_headers_for({"wsgi.url_scheme": "http"}, dev=False)
    by_name = {k: v for k, v in headers}
    assert "Content-Security-Policy-Report-Only" in by_name
    assert "Content-Security-Policy" not in by_name
    assert "default-src 'self'" in by_name["Content-Security-Policy-Report-Only"]


def test_dev_mode_has_no_default_csp():
    """Dev doesn't need the noise — no forced CSP header locally."""
    headers = security_headers_for({"wsgi.url_scheme": "http"}, dev=True)
    names = {k for k, _ in headers}
    assert "Content-Security-Policy" not in names
    assert "Content-Security-Policy-Report-Only" not in names


def test_explicit_csp_in_extra_wins_over_default():
    """An operator-configured `security.headers.extra` CSP is never overridden."""
    headers = security_headers_for(
        {"wsgi.url_scheme": "http"},
        extra=[("Content-Security-Policy", "default-src 'none'")],
        dev=False,
    )
    values = [v for k, v in headers if k == "Content-Security-Policy"]
    assert values == ["default-src 'none'"]
    assert not any(k == "Content-Security-Policy-Report-Only" for k, _ in headers)


def test_explicit_csp_report_only_in_extra_also_wins():
    headers = security_headers_for(
        {"wsgi.url_scheme": "http"},
        extra=[("Content-Security-Policy-Report-Only", "default-src 'none'")],
        dev=False,
    )
    values = [v for k, v in headers if k == "Content-Security-Policy-Report-Only"]
    assert values == ["default-src 'none'"]


# ---------------- HSTS over resolved scheme (proxy-aware, anti-spoof) ----------------


def test_hsts_fires_over_resolved_https_behind_trusted_proxy():
    headers = security_headers_for(
        _https_via_proxy(), dev=False, trust_proxy=True,
    )
    names = {k for k, _ in headers}
    assert "Strict-Transport-Security" in names


def test_hsts_anti_spoof_ignored_without_trust_proxy():
    """A spoofed X-Forwarded-Proto: https must NOT force HSTS on when the
    deployment hasn't opted into trusting a reverse proxy."""
    headers = security_headers_for(
        _https_via_proxy(), dev=False, trust_proxy=False,
    )
    names = {k for k, _ in headers}
    assert "Strict-Transport-Security" not in names


def test_hsts_still_gated_on_plain_http_with_trust_proxy_on():
    headers = security_headers_for(
        {"wsgi.url_scheme": "http"}, dev=False, trust_proxy=True,
    )
    names = {k for k, _ in headers}
    assert "Strict-Transport-Security" not in names


def test_dev_mode_never_forces_hsts_even_over_https():
    headers = security_headers_for({"wsgi.url_scheme": "https"}, dev=True)
    names = {k for k, _ in headers}
    assert "Strict-Transport-Security" not in names


def test_existing_behavior_hsts_over_direct_https_unchanged():
    """No proxy involved: direct https still gets HSTS in production, as before."""
    headers = security_headers_for({"wsgi.url_scheme": "https"}, dev=False)
    names = {k for k, _ in headers}
    assert "Strict-Transport-Security" in names


# ---------------- wrap_start_response threads dev/trust_proxy through ----------------


def test_wrap_start_response_threads_trust_proxy_for_hsts():
    captured = []

    def sr(status, headers):
        captured.append(headers)

    wrapped = wrap_start_response(
        sr, _https_via_proxy(), dev=False, trust_proxy=True,
    )
    wrapped("200 OK", [])
    keys = {k for k, _ in captured[0]}
    assert "Strict-Transport-Security" in keys


def test_wrap_start_response_respects_dev_flag():
    captured = []

    def sr(status, headers):
        captured.append(headers)

    wrapped = wrap_start_response(sr, {"wsgi.url_scheme": "http"}, dev=True)
    wrapped("200 OK", [])
    keys = {k for k, _ in captured[0]}
    assert "Content-Security-Policy-Report-Only" not in keys


# ---------------- MiddlewareSettings threads `dev` ----------------


def test_middleware_settings_dev_defaults_false():
    s = MiddlewareSettings.from_yaml(limits={}, security={})
    assert s.dev is False


def test_middleware_settings_dev_true_when_passed():
    s = MiddlewareSettings.from_yaml(limits={}, security={}, dev=True)
    assert s.dev is True


def test_default_csp_constant_is_report_only_and_self_scoped():
    assert "default-src 'self'" in DEFAULT_CSP_REPORT_ONLY
    assert "script-src" in DEFAULT_CSP_REPORT_ONLY
