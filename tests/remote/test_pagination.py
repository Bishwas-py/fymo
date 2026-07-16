"""Cursor pagination helpers: opaque cursor round-trip + fetch-one-extra split."""
import pytest
from fymo.remote.errors import RemoteError
from fymo.remote.pagination import encode_cursor, decode_cursor, paginate


def test_cursor_round_trip_single_value():
    cur = encode_cursor("2026-01-01T00:00:00Z")
    assert decode_cursor(cur) == ["2026-01-01T00:00:00Z"]


def test_cursor_round_trip_multiple_values():
    cur = encode_cursor("2026-01-01T00:00:00Z", "welcome-to-fymo")
    assert decode_cursor(cur) == ["2026-01-01T00:00:00Z", "welcome-to-fymo"]


def test_cursor_round_trip_numeric_value():
    assert decode_cursor(encode_cursor(42)) == [42]


def test_cursor_is_urlsafe_and_unpadded():
    cur = encode_cursor("value with spaces & specials?/+~")
    assert "=" not in cur and "+" not in cur and "/" not in cur


def test_cursor_expect_arity():
    cur = encode_cursor("a", "b")
    assert decode_cursor(cur, expect=2) == ["a", "b"]
    with pytest.raises(RemoteError) as exc:
        decode_cursor(cur, expect=1)
    assert exc.value.status == 400
    assert exc.value.code == "bad_cursor"


@pytest.mark.parametrize("garbage", [
    "",
    "not base64 at all!!!",
    "aGVsbG8",        # base64 of "hello", not JSON
    "e30",            # base64 of "{}", JSON but not a list
    "W10",            # base64 of "[]", empty list
    "W1siYSJdLHt9XQ", # base64 of '[["a"],{}]', nested values are not sort keys
    12345,            # not even a string
    None,
])
def test_garbage_cursor_raises_remote_error(garbage):
    with pytest.raises(RemoteError) as exc:
        decode_cursor(garbage)
    assert exc.value.status == 400
    assert exc.value.code == "bad_cursor"


def _rows(n):
    return [{"id": i, "ts": f"2026-01-{i:02d}"} for i in range(n, 0, -1)]


def test_paginate_full_page_with_extra_row():
    rows = _rows(4)  # fetched with limit 3 + 1
    page = paginate(rows, 3, key=lambda r: r["ts"])
    assert page["items"] == rows[:3]
    assert page["next_cursor"] == encode_cursor(rows[2]["ts"])


def test_paginate_last_page_exact():
    rows = _rows(3)  # limit 3, no extra row came back
    page = paginate(rows, 3, key=lambda r: r["ts"])
    assert page["items"] == rows
    assert page["next_cursor"] is None


def test_paginate_short_page():
    rows = _rows(2)
    page = paginate(rows, 3, key=lambda r: r["ts"])
    assert page["items"] == rows
    assert page["next_cursor"] is None


def test_paginate_empty():
    page = paginate([], 3, key=lambda r: r["ts"])
    assert page["items"] == []
    assert page["next_cursor"] is None


def test_paginate_composite_key():
    rows = _rows(4)
    page = paginate(rows, 3, key=lambda r: (r["ts"], r["id"]))
    last = rows[2]
    assert page["next_cursor"] == encode_cursor(last["ts"], last["id"])
    assert decode_cursor(page["next_cursor"], expect=2) == [last["ts"], last["id"]]
