"""Fymo auth: mechanism, not model.

Identity is an opaque uid string produced by app-defined resolvers in
app/auth/ (auto-discovered); the framework owns no user shape and no user
table. Scaffold a starting point you own with `fymo generate auth`.

Public API:

    from fymo.auth import identify, Identity, current_uid, require_auth

    @identify
    def by_api_key(event):             # event: ResolverEvent
        uid = lookup(event.headers.get("x-api-key"))
        return Identity(uid=uid) if uid else None

    @require_auth                      # 401 envelope when anonymous
    def create_post(title: str) -> dict:
        uid = current_uid()            # never None inside @require_auth
        ...

Plus identity_extras()/register_identity_extras_hook for app data attached
to the identity, public_identity for the client-visible projection, and
the primitives: hash_password/verify_password (scrypt) and
sign_token/verify_token (HMAC-signed uid tokens under FYMO_SECRET).
"""
from fymo.auth.context import (
    AuthRequired,
    identity_extras,
    register_identity_extras_hook,
    require_auth,
)
from fymo.auth.identity import Identity, ResolverEvent, current_uid, identify
from fymo.auth.passwords import hash_password, verify_password
from fymo.auth.public import public_identity
from fymo.auth.verify_token import sign_token, verify_token

__all__ = [
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
]
