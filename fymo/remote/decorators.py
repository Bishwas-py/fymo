"""Opt-in marker for app/remote/*.py functions.

By default every public, type-annotated top-level function in an app
remote module is exposed to the browser (see `discovery._collect_module_functions`).
That's convenient but means an internal helper defined alongside real
endpoints is silently callable. When `remote.explicit_optin` is enabled in
fymo.yml, only functions marked `@remote` are discovered and dispatchable —
this decorator sets that marker.
"""
from typing import Callable, TypeVar

F = TypeVar("F", bound=Callable)


def remote(fn: F) -> F:
    """Mark a function as an explicit remote endpoint.

    Returns the function unchanged (no wrapping) — it only stamps
    `__fymo_remote__ = True` so discovery/router can recognize it when
    `remote.explicit_optin` is on. A no-op when opt-in is off.
    """
    fn.__fymo_remote__ = True
    return fn
