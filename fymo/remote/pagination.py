"""Cursor pagination helpers for remote functions that return lists.

The convention: a paginated function takes `(cursor: str | None = None,
limit: int = 20)` and returns `{"items": [...], "next_cursor": str | None}`.
The cursor is opaque to the client: base64url-encoded JSON of the last-seen
sort-key value(s). Fetch `limit + 1` rows ("WHERE sort_key < :last ORDER BY
sort_key DESC LIMIT :limit + 1") and let `paginate` split off the extra row
into `next_cursor`. These helpers know nothing about any database; the query
stays in app code.
"""
import base64
import json
from typing import Any, Callable

from fymo.remote.errors import RemoteError

_CURSOR_MAX = 1024


def _bad_cursor() -> RemoteError:
    return RemoteError("invalid pagination cursor", status=400, code="bad_cursor")


def encode_cursor(*values: Any) -> str:
    """Encode one or more sort-key values into an opaque cursor string."""
    raw = json.dumps(list(values), separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def decode_cursor(cursor: str, *, expect: "int | None" = None) -> list:
    """Decode a cursor back into its sort-key values.

    Any malformed input (wrong type, bad base64, non-JSON, not a non-empty
    list, wrong arity when `expect` is given) raises a RemoteError that the
    router turns into a 400 "bad_cursor" envelope instead of a 500.
    """
    if not isinstance(cursor, str) or not cursor or len(cursor) > _CURSOR_MAX:
        raise _bad_cursor()
    try:
        pad = "=" * (-len(cursor) % 4)
        values = json.loads(base64.urlsafe_b64decode(cursor + pad).decode("utf-8"))
    except Exception:
        raise _bad_cursor()
    if not isinstance(values, list) or not values:
        raise _bad_cursor()
    if expect is not None and len(values) != expect:
        raise _bad_cursor()
    # Sort-key values are scalars; nested JSON in a cursor is garbage and
    # must not leak through to whatever query binds the values.
    if not all(v is None or isinstance(v, (str, int, float, bool)) for v in values):
        raise _bad_cursor()
    return values


def paginate(rows: list, limit: int, *, key: Callable[[Any], Any]) -> dict:
    """Split a fetch-one-extra row list into the page dict.

    `rows` holds up to `limit + 1` rows. If the extra row is present there
    is a next page: keep `limit` rows and encode the last kept row's sort
    key(s) as `next_cursor`. `key` maps a row to its sort-key value, or a
    tuple of values for composite sort keys.
    """
    items = rows[:limit]
    next_cursor = None
    if len(rows) > limit and items:
        values = key(items[-1])
        if not isinstance(values, tuple):
            values = (values,)
        next_cursor = encode_cursor(*values)
    return {"items": items, "next_cursor": next_cursor}
