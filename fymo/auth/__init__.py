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
"""
from fymo.auth.context import (
    current_user,
    require_auth,
    AuthRequired,
    identity_extras,
    register_identity_extras_hook,
)
from fymo.auth.passwords import hash_password, verify_password
from fymo.auth.store import User, UserStore, SqliteUserStore, EmailAlreadyExists

__all__ = [
    "current_user",
    "require_auth",
    "AuthRequired",
    "identity_extras",
    "register_identity_extras_hook",
    "hash_password",
    "verify_password",
    "User",
    "UserStore",
    "SqliteUserStore",
    "EmailAlreadyExists",
]
