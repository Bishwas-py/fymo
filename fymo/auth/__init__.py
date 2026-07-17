"""Fymo auth: pre-opinionated, extensible.

Public API:

    from fymo.auth import current_user, require_auth, User
    from fymo.auth import hash_password, verify_password

    @require_auth
    def create_post(title: str, content: str):
        user = current_user()        # never None inside @require_auth
        ...

The fymo.yml `auth:` section enables it and points at custom stores when
needed. See `fymo.auth.store.UserStore` Protocol for the seam.

Identity resolvers (issue #80, new surface):

    from fymo.auth import identify, Identity, current_uid

    @identify
    def by_api_key(event):             # event: ResolverEvent
        uid = lookup(event.headers.get("x-api-key"))
        return Identity(uid=uid) if uid else None

    uid = current_uid()                # str | None, inside a request scope

Plus the promoted primitives: hash_password/verify_password and
sign_token/verify_token.
"""
from fymo.auth.context import (
    current_user,
    require_auth,
    AuthRequired,
    identity_extras,
    register_identity_extras_hook,
)
from fymo.auth.identity import Identity, ResolverEvent, current_uid, identify
from fymo.auth.passwords import hash_password, verify_password
from fymo.auth.public import public_identity
from fymo.auth.store import User, UserStore, SqliteUserStore, EmailAlreadyExists
from fymo.auth.verify_token import sign_token, verify_token

__all__ = [
    "current_user",
    "require_auth",
    "AuthRequired",
    "identity_extras",
    "register_identity_extras_hook",
    "Identity",
    "ResolverEvent",
    "identify",
    "current_uid",
    "public_identity",
    "hash_password",
    "verify_password",
    "sign_token",
    "verify_token",
    "User",
    "UserStore",
    "SqliteUserStore",
    "EmailAlreadyExists",
]
