"""Built-in email/password provider — the default credential flow.

The signup/login/logout/me functions already live in `fymo.auth.remote`; this
provider just exposes them as its remote-function surface. No behavior change,
it only makes password one provider among many.
"""
from __future__ import annotations

from typing import Callable, Dict

from fymo.auth import remote as auth_remote
from fymo.auth.providers.base import BaseProvider


class PasswordProvider(BaseProvider):
    id = "password"
    # Exposed to the frontend as $remote/auth (the established import path).
    remote_module = "auth"

    def remote_functions(self) -> Dict[str, Callable]:
        return {
            "signup": auth_remote.signup,
            "login": auth_remote.login,
            "logout": auth_remote.logout,
            "me": auth_remote.me,
            "request_email_verification": auth_remote.request_email_verification,
            "verify_email": auth_remote.verify_email,
            "request_password_reset": auth_remote.request_password_reset,
            "reset_password": auth_remote.reset_password,
        }
