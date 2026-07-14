"""The AuthProvider seam.

A provider contributes only the surface it needs — the framework never
branches on provider *type*, it just calls the three hooks:

  * remote_functions() — named functions merged into the $remote/auth client
    (credential flows: password login/signup).
  * http_routes()      — GET/POST routes under /auth/<id>/... (OAuth redirect
    + callback, which can't be remote-function POSTs).
  * resolve_session()  — map a request event to a User from a request-borne
    token, or None (hosted/token flows like Clerk).

Subclass `BaseProvider` and override what you use; the rest stays inert.
"""
from __future__ import annotations

from typing import Callable, Dict, List, Optional, Protocol, runtime_checkable

from fymo.auth.store import User
from fymo.core.http import HttpRoute  # canonical definition; re-exported here
                                        # for back-compat since providers have
                                        # always imported it from this module.


@runtime_checkable
class AuthProvider(Protocol):
    id: str

    def remote_functions(self) -> Dict[str, Callable]: ...
    def http_routes(self) -> List[HttpRoute]: ...
    def resolve_session(self, event: dict) -> Optional[User]: ...


class BaseProvider:
    """Inert defaults so a provider only implements the axis it participates in."""

    id: str = ""
    # Module name under which this provider's remote_functions() are exposed to
    # the frontend ($remote/<remote_module>). Defaults to id when unset.
    remote_module: str = ""

    def remote_functions(self) -> Dict[str, Callable]:
        return {}

    def http_routes(self) -> List[HttpRoute]:
        return []

    def resolve_session(self, event: dict) -> Optional[User]:
        return None

    @classmethod
    def is_configured(cls) -> bool:
        """Whether this provider has what it needs (e.g. required env vars)
        to be constructed. Only consulted when a fymo.yml entry opts in with
        `required: auto`; default True keeps every existing provider
        unaffected, since most providers have no optional-configuration
        story at all."""
        return True
