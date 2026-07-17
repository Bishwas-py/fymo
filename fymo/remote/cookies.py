"""Public response-cookie seam for remote functions (issue #80).

set_cookie()/clear_cookie() queue Set-Cookie headers onto the pending
scope the remote router opens around every dispatch (see
fymo.auth.context.start_auth_scope / handle_remote step 8). This is the
seam app-owned auth code uses to establish or drop a session; the legacy
queue helpers in fymo.auth.context are User-shaped and go with the model.
"""
from __future__ import annotations

import re
from typing import Optional

_NAME_RE = re.compile(r"^[A-Za-z0-9!#$%&'*+.^_`|~-]+$")
_VALUE_RE = re.compile(r"^[A-Za-z0-9!#$%&'()*+./:<=>?@\[\]^_`{|}~-]*$")
_SAME_SITE = ("Lax", "Strict", "None")


def _request_scheme() -> str:
    from fymo.remote.context import _current_event
    event = _current_event.get()
    return (event or {}).get("scheme", "http")


def _queue(header: str) -> None:
    from fymo.auth.context import _pending_cookies
    pending = _pending_cookies.get()
    if pending is None:
        raise RuntimeError(
            "set_cookie() called outside a remote request; response cookies "
            "can only be queued while a remote function is handling a request"
        )
    pending.append(header)


def set_cookie(
    name: str,
    value: str,
    *,
    max_age: Optional[int] = None,
    path: str = "/",
    http_only: bool = True,
    same_site: str = "Lax",
    secure: Optional[bool] = None,
) -> None:
    """Queue a Set-Cookie header on the current remote response.

    `secure=None` (the default) sets the Secure attribute whenever the
    resolved request scheme is https; request_scope() already folds
    X-Forwarded-Proto into that scheme when trust_proxy is on, so this is
    proxy-aware. Raises ValueError on characters that would corrupt the
    header, RuntimeError outside a remote request.
    """
    if not name or not _NAME_RE.match(name):
        raise ValueError(f"invalid cookie name {name!r}")
    if not _VALUE_RE.match(value):
        raise ValueError(
            f"invalid cookie value {value!r}; only RFC 6265 cookie-octets are allowed"
        )
    if same_site not in _SAME_SITE:
        raise ValueError(f"same_site must be one of {_SAME_SITE}, got {same_site!r}")
    parts = [f"{name}={value}", f"Path={path}"]
    if max_age is not None:
        parts.append(f"Max-Age={int(max_age)}")
    parts.append(f"SameSite={same_site}")
    if http_only:
        parts.append("HttpOnly")
    if secure is None:
        secure = _request_scheme() == "https"
    if secure:
        parts.append("Secure")
    _queue("; ".join(parts))


def clear_cookie(name: str, *, path: str = "/") -> None:
    """Queue a Set-Cookie that expires `name` immediately."""
    set_cookie(name, "", max_age=0, path=path)
