"""Built-in auth remote functions.

These live in `fymo/auth/remote.py` and are wired into the discovery /
routing layer as the system-shipped `auth` module. Apps don't create any
file under `app/remote/` for these — they just import from `$remote/auth`
on the frontend and the functions resolve here on the backend.

Function contracts (all use the existing /_fymo/remote envelope):

  signup(email: str, password: str) -> UserPublic
  login(email: str, password: str) -> UserPublic
  logout() -> {ok: True}
  me() -> UserPublic | None
  request_email_verification() -> {ok: True}
  verify_email(token: str) -> {ok: True, email_verified: True}
  request_password_reset(email: str) -> {ok: True}
  reset_password(token: str, new_password: str) -> {ok: True}

UserPublic intentionally never returns password_hash or fymo_uid.
"""
from __future__ import annotations

import logging
from typing import Optional, TypedDict

from fymo.auth.context import (
    AuthRequired,
    current_user,
    get_email_sender,
    get_user_store,
    queue_session_clear,
    queue_session_cookie,
)
from fymo.auth.passwords import DECOY_HASH, hash_password, verify_password
from fymo.auth.store import EmailAlreadyExists, User
from fymo.auth.verify_token import make_reset_token, make_verify_token
from fymo.remote.context import request_event
from fymo.remote.errors import Conflict, RemoteError


# Minimum policy. Length only — no character-class rules. Matches NIST
# SP 800-63B guidance (longer is the point; complexity is theater).
MIN_PASSWORD_LENGTH = 8

_logger = logging.getLogger("fymo.auth")


class UserPublic(TypedDict):
    id: int
    email: str
    email_verified: bool
    created_at: str


def _public(user: User) -> UserPublic:
    return {
        "id": user.id,
        "email": user.email,
        "email_verified": user.email_verified,
        "created_at": user.created_at,
    }


class InvalidCredentials(RemoteError):
    """Generic auth failure. Same message for "no such email" and "wrong
    password" so an attacker can't enumerate registered emails by response."""
    def __init__(self):
        super().__init__("invalid email or password", status=401, code="invalid_credentials")


def _validate_email(email: str) -> str:
    if not isinstance(email, str):
        raise RemoteError("email must be a string", status=400, code="bad_input")
    email = email.strip()
    if not email or "@" not in email or len(email) > 320:
        raise RemoteError("email must be a valid address", status=400, code="bad_input")
    return email.lower()


def _validate_password(password: str) -> str:
    if not isinstance(password, str):
        raise RemoteError("password must be a string", status=400, code="bad_input")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise RemoteError(
            f"password must be at least {MIN_PASSWORD_LENGTH} characters",
            status=400, code="bad_input",
        )
    return password


# --------------- public remote functions ---------------


def signup(email: str, password: str) -> UserPublic:
    """Create a new account. Sets fymo_session on success.

    The new user starts with `email_verified=False`; a signed verification
    token is issued and handed to the `EmailSender` seam (default: logged,
    not mailed — see `fymo/auth/email.py`) so the account can be verified via
    `verify_email(token)`. Sending that email is best-effort: if the sender
    raises, signup still succeeds and returns the new session (see
    `_issue_and_send_verification`) — the account is already committed by the
    time the send is attempted, so failing the whole call here would strand
    the caller with a created-but-unconfirmed account and no way to retry
    signup (a retry would hit 409 email already registered).
    """
    email = _validate_email(email)
    password = _validate_password(password)
    store = get_user_store()
    try:
        user = store.create(email=email, password_hash=hash_password(password))
    except EmailAlreadyExists:
        # Same code as login's failure, so signup probes can't enumerate
        # either — but the *status* (409 vs 200) still differs from a fresh
        # signup, which is itself a residual enumeration channel. Closing
        # that fully would mean signup always returns a 200-shaped
        # "verification sent" response regardless of whether the email was
        # already registered; that's a bigger response-shape change than
        # this task's scope (wiring the verification flow itself), so it's
        # left as a documented gap rather than folded in here.
        raise Conflict("email already registered")
    _link_anonymous_uid(user.id)
    _issue_and_send_verification(user)
    queue_session_cookie(user.id, user.session_epoch, environ=_environ_from_event())
    return _public(user)


def login(email: str, password: str) -> UserPublic:
    """Verify credentials and start a session."""
    email = _validate_email(email)
    password = _validate_password(password)
    store = get_user_store()
    user = store.get_by_email(email)
    if user is None or user.password_hash is None:
        # Timing equalization: an unknown email (or a user with no password
        # hash, e.g. OAuth-only) must cost the same as a wrong-password
        # attempt on a real account, or the response latency alone lets an
        # attacker enumerate registered emails despite the identical error
        # message. Run a real scrypt verify against a fixed decoy hash —
        # result is always False, it exists only to burn the same ~50ms.
        verify_password(password, DECOY_HASH)
        raise InvalidCredentials()
    if not verify_password(password, user.password_hash):
        raise InvalidCredentials()
    _link_anonymous_uid(user.id)
    queue_session_cookie(user.id, user.session_epoch, environ=_environ_from_event())
    return _public(user)


def logout() -> dict:
    """Revoke the session server-side and clear the cookie.

    Bumping the user's epoch invalidates every outstanding token for them, so a
    captured cookie can't be replayed after logout. Idempotent — when no valid
    session is present there's nothing to revoke, and we still clear the cookie.
    """
    user = current_user()
    if user is not None:
        get_user_store().bump_session_epoch(user.id)
    queue_session_clear(environ=_environ_from_event())
    return {"ok": True}


def me() -> Optional[UserPublic]:
    """Return the authenticated user, or None when no session is present."""
    user = current_user()
    return _public(user) if user is not None else None


def request_email_verification() -> dict:
    """Re-issue and resend a verification email for the signed-in user.

    Requires an active session. Generating a new token invalidates any
    previously-sent one (see `UserStore.set_verify_token`), so only the most
    recently requested link works.
    """
    user = current_user()
    if user is None:
        raise AuthRequired()
    if user.email_verified:
        return {"ok": True, "already_verified": True}
    _issue_and_send_verification(user)
    return {"ok": True}


def verify_email(token: str) -> dict:
    """Consume a verification token, flipping `email_verified` to True.

    Signature forgery, expiry, and replay (the token already having been
    consumed, or superseded by a newer one) all collapse to the same
    "invalid_token" error — no detail is leaked about which check failed.
    """
    if not isinstance(token, str) or not token:
        raise RemoteError("token must be a string", status=400, code="bad_input")
    user_id = get_user_store().consume_verify_token(token)
    if user_id is None:
        raise RemoteError("invalid or expired token", status=400, code="invalid_token")
    return {"ok": True, "email_verified": True}


def request_password_reset(email: str) -> dict:
    """Issue a password-reset token and send it, but ALWAYS return the same
    200-shaped `{"ok": True}` response — whether or not `email` belongs to a
    registered account. Revealing existence via response or status here would
    let an attacker enumerate registered emails, the same concern `login`
    handles for credential checks. Sending the email is the only thing that
    differs, and only happens server-side where the caller can't observe it.
    """
    email = _validate_email(email)
    user = get_user_store().get_by_email(email)
    if user is not None:
        _issue_and_send_reset(user)
    return {"ok": True}


def reset_password(token: str, new_password: str) -> dict:
    """Consume a password-reset token and set a new password hash.

    The new password is validated before the token is consumed, so a request
    with a valid token but a too-short password doesn't burn the (single-use)
    token — the caller can retry with a stronger password using the same link.
    `set_password_hash` bumps `session_epoch`, which revokes every session
    issued before this call — a captured cookie stops authenticating the
    moment the password changes, same as a password change via any other
    path.
    """
    if not isinstance(token, str) or not token:
        raise RemoteError("token must be a string", status=400, code="bad_input")
    new_password = _validate_password(new_password)
    user_id = get_user_store().consume_reset_token(token)
    if user_id is None:
        raise RemoteError("invalid or expired token", status=400, code="invalid_token")
    get_user_store().set_password_hash(user_id, hash_password(new_password))
    return {"ok": True}


# --------------- internals ---------------


def _issue_and_send_verification(user: User) -> None:
    """Issue a verify token and hand it to the EmailSender seam, best-effort.

    The token is minted and persisted (so a later `request_email_verification`
    or manual resend can still work) before the send is attempted. Delivery
    itself is not allowed to fail the caller: a real (non-logging) EmailSender
    can raise on a transient error (SMTP timeout, provider outage, ...), and
    since this always runs after the account row is already committed
    (signup) or after a session is already established (resend), letting that
    exception propagate would turn a delivery hiccup into a 500 for an
    operation that already succeeded — for signup specifically, a retry would
    then hit `409 email already registered` with no way back in except login.
    So the send is wrapped: on failure we log it (never the token/link itself,
    only identifying context) and return normally either way. Both call sites
    (signup, request_email_verification) get this guarantee for free.
    """
    token = make_verify_token(user.id)
    get_user_store().set_verify_token(user.id, token)
    link = f"/verify-email?token={token}"
    try:
        get_email_sender().send_verification(user.email, link)
    except Exception:
        _logger.warning(
            "verification email send failed for user_id=%s; "
            "account/session unaffected, email delivery is best-effort",
            user.id,
            exc_info=True,
        )


def _issue_and_send_reset(user: User) -> None:
    """Issue a reset token and hand it to the EmailSender seam, best-effort.

    Mirrors `_issue_and_send_verification`: the token is minted and persisted
    first, then delivery is attempted but never allowed to fail the caller —
    `request_password_reset` must return the same `{"ok": True}` regardless of
    whether a real (non-logging) EmailSender hiccups, or an attacker could
    distinguish "sender raised" from "no such account" by response shape.
    """
    token = make_reset_token(user.id)
    get_user_store().set_reset_token(user.id, token)
    link = f"/reset-password?token={token}"
    try:
        get_email_sender().send_password_reset(user.email, link)
    except Exception:
        _logger.warning(
            "password reset email send failed for user_id=%s; "
            "response is unaffected, email delivery is best-effort",
            user.id,
            exc_info=True,
        )


def _link_anonymous_uid(user_id: int) -> None:
    """Attach the current request's fymo_uid to the user, idempotent.

    Runs on first login and every login afterwards — but claim_fymo_uid()
    only writes when the column is NULL. Cheap, makes anonymous activity
    (reactions, comments) become "owned" by the new account.
    """
    ev = request_event()
    if ev.uid:
        get_user_store().claim_fymo_uid(user_id, ev.uid)


def _environ_from_event() -> dict:
    """Reconstruct the wsgi.url_scheme bit of environ for cookie building.

    The auth functions only care about scheme (for the Secure flag); pulling
    the full environ through every call would be noisy. The cookie builders
    only ever read `wsgi.url_scheme`.

    The scheme itself is resolved once, upstream, by `request_scope()` (see
    `fymo/remote/context.py`), which already honors `X-Forwarded-Proto` when
    `trust_proxy` is enabled — so behind a TLS-terminating proxy this reads
    "https" even though the raw `wsgi.url_scheme` on the socket is "http".
    Default to "http" if called outside a scope for any reason: the safe
    default is Secure=False, not a forged Secure flag.
    """
    ev = request_event()
    from fymo.remote.context import _current_event
    payload = _current_event.get() or {}
    return {"wsgi.url_scheme": payload.get("scheme", "http")}
