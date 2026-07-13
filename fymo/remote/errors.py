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
