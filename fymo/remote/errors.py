"""Domain error types for remote functions. Each maps to an HTTP status."""


class RemoteError(Exception):
    """Base class. Translates to a JSON response with the given status + code."""
    status: int = 500
    code: str = "internal"

    def __init__(self, message: str, *, status: int | None = None, code: str | None = None):
        super().__init__(message)
        if status is not None:
            self.status = status
        if code is not None:
            self.code = code


class NotFound(RemoteError):
    status = 404
    code = "not_found"


class Unauthorized(RemoteError):
    status = 401
    code = "unauthorized"


class Forbidden(RemoteError):
    status = 403
    code = "forbidden"


class Conflict(RemoteError):
    status = 409
    code = "conflict"


class Redirect(RemoteError):
    """Raised by a controller's getContext() or a remote function to send the
    client elsewhere instead of returning a result.

    Not an error, but subclasses RemoteError so it travels the exact seam
    NotFound/Unauthorized/etc already use: the router, the SSR renderer, and
    the soft-nav data endpoint each catch RemoteError around
    controller/remote-function invocation, and special-case this subclass to
    produce a redirect wire form (a real 30x + Location header for SSR, a
    {"type": "redirect", ...} envelope for remote calls) instead of the
    generic error envelope.
    """
    status = 303
    code = "redirect"

    def __init__(self, location: str, status: int = 303):
        super().__init__(f"redirect to {location}", status=status, code="redirect")
        self.location = location
