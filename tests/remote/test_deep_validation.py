"""Deep argument validation: container element types and structured params
(dataclass / TypedDict / NamedTuple) must be validated, not pass-through.

Before this, `list[int]` only checked the value was *a* list — element types
were never inspected, so `["x", {}]` sailed through. Dataclass/TypedDict/
NamedTuple params were pass-through entirely: any dict reached the function
body untouched, whatever its shape.

With pydantic installed, structured types are validated via `TypeAdapter`
(mirroring the existing pydantic BaseModel path, which already raises
`pydantic.ValidationError` — the router maps that to a 422 `validation`
envelope). Without pydantic, a stdlib structural check enforces required
fields and recurses into declared field types via `_coerce_value`. The
stdlib fallback is best-effort: it does not replicate every typing edge case
pydantic covers (forward refs needing extra namespace context, complex
generic aliases), but it does reject the common shapes of bad input —
missing required fields and wrong field types.

Unknown extra keys on a dataclass/TypedDict are ignored (not rejected) on
both paths — this matches pydantic TypeAdapter's default behavior for those
two types, which cannot be reliably forced into "forbid extras" mode without
mutating the caller's class. NamedTuple is the exception: pydantic already
rejects extra keys there (validated like a callable's keyword arguments),
and the stdlib fallback matches that.

Dict keys arrive as strings on the wire (JSON/devalue only produce string
object keys), so `Dict[K, V]` with non-str `K` coerces the string key to
`K` via `K`'s constructor before validating (`Dict[int, V]` parses
`{"1": 2}` -> `{1: 2}`).
"""
import base64
import inspect
import io
import json
import typing
from dataclasses import dataclass
from typing import Dict, List, NamedTuple, Tuple, TypedDict

import pytest

from fymo.remote import adapters, devalue
from fymo.remote.adapters import validate_args
from fymo.remote.router import handle_remote


def _hints_for(fn):
    return typing.get_type_hints(fn, include_extras=True)


def _validate(fn, args):
    sig = inspect.signature(fn)
    hints = _hints_for(fn)
    return validate_args(args, sig, hints)


# ---------------------------------------------------------------------------
# container element validation
# ---------------------------------------------------------------------------

def test_list_int_rejects_bad_elements():
    def fn(xs: List[int]) -> int: return 0

    with pytest.raises(TypeError):
        _validate(fn, [["x", {}]])


def test_list_int_accepts_valid_elements():
    def fn(xs: List[int]) -> int: return sum(xs)

    args = _validate(fn, [[1, 2, 3]])
    assert args == [[1, 2, 3]]


def test_dict_str_int_rejects_bad_value():
    def fn(m: Dict[str, int]) -> int: return 0

    with pytest.raises(TypeError):
        _validate(fn, [{"a": "not-an-int"}])


def test_dict_str_int_accepts_valid_values():
    def fn(m: Dict[str, int]) -> int: return 0

    args = _validate(fn, [{"a": 1, "b": 2}])
    assert args == [{"a": 1, "b": 2}]


def test_tuple_fixed_length_element_types_rejects_mismatch():
    def fn(t: Tuple[int, str]) -> int: return 0

    with pytest.raises(TypeError):
        _validate(fn, [[1, 2]])  # second element should be str


def test_tuple_fixed_length_element_types_accepts_match():
    def fn(t: Tuple[int, str]) -> int: return 0

    args = _validate(fn, [[1, "ok"]])
    assert args == [[1, "ok"]]


# ---------------------------------------------------------------------------
# structured types: dataclass
# ---------------------------------------------------------------------------

@dataclass
class Row:
    slug: str
    n: int


def test_dataclass_rejects_wrong_typed_field():
    def fn(row: Row) -> str: return row.slug

    with pytest.raises(Exception):
        _validate(fn, [{"slug": "x", "n": "not-an-int"}])


def test_dataclass_rejects_missing_required_field():
    def fn(row: Row) -> str: return row.slug

    with pytest.raises(Exception):
        _validate(fn, [{"slug": "x"}])


def test_dataclass_accepts_valid_dict():
    def fn(row: Row) -> str: return row.slug

    args = _validate(fn, [{"slug": "x", "n": 5}])
    assert args[0].slug == "x"
    assert args[0].n == 5


def test_list_of_dataclass_rejects_bad_element():
    def fn(rows: List[Row]) -> int: return len(rows)

    with pytest.raises(Exception):
        _validate(fn, [[{"slug": "x", "n": "bad"}]])


def test_list_of_dataclass_accepts_valid_elements():
    def fn(rows: List[Row]) -> int: return len(rows)

    args = _validate(fn, [[{"slug": "x", "n": 1}, {"slug": "y", "n": 2}]])
    assert len(args[0]) == 2
    assert args[0][0].slug == "x"
    assert args[0][1].n == 2


# ---------------------------------------------------------------------------
# structured types: TypedDict
# ---------------------------------------------------------------------------

class RowDict(TypedDict):
    slug: str
    n: int


def test_typeddict_rejects_wrong_typed_field():
    def fn(row: RowDict) -> str: return row["slug"]

    with pytest.raises(Exception):
        _validate(fn, [{"slug": "x", "n": "bad"}])


def test_typeddict_rejects_missing_required_key():
    def fn(row: RowDict) -> str: return row["slug"]

    with pytest.raises(Exception):
        _validate(fn, [{"slug": "x"}])


def test_typeddict_accepts_valid_dict():
    def fn(row: RowDict) -> str: return row["slug"]

    args = _validate(fn, [{"slug": "x", "n": 5}])
    assert args[0] == {"slug": "x", "n": 5}


# ---------------------------------------------------------------------------
# structured types: NamedTuple
# ---------------------------------------------------------------------------

class RowTuple(NamedTuple):
    slug: str
    n: int


def test_namedtuple_rejects_wrong_typed_field():
    def fn(row: RowTuple) -> str: return row.slug

    with pytest.raises(Exception):
        _validate(fn, [{"slug": "x", "n": "bad"}])


def test_namedtuple_accepts_valid_dict():
    def fn(row: RowTuple) -> str: return row.slug

    args = _validate(fn, [{"slug": "x", "n": 5}])
    assert args[0].slug == "x"
    assert args[0].n == 5


# ---------------------------------------------------------------------------
# stdlib fallback (pydantic absent) — container recursion and structured
# validation must both still work without pydantic installed.
# ---------------------------------------------------------------------------

def test_stdlib_fallback_still_validates_containers(monkeypatch):
    monkeypatch.setattr(adapters, "_has_pydantic", False)
    monkeypatch.setattr(adapters, "pydantic", None)

    def fn(xs: List[int]) -> int: return sum(xs)

    with pytest.raises(TypeError):
        _validate(fn, [["x"]])
    args = _validate(fn, [[1, 2, 3]])
    assert args == [[1, 2, 3]]


def test_stdlib_fallback_validates_namedtuple(monkeypatch):
    """Fix 2 (review): the NamedTuple stdlib fallback path exists and works
    but previously had no dedicated test."""
    monkeypatch.setattr(adapters, "_has_pydantic", False)
    monkeypatch.setattr(adapters, "pydantic", None)

    def fn(row: RowTuple) -> str: return row.slug

    args = _validate(fn, [{"slug": "x", "n": 5}])
    assert args[0].slug == "x"
    assert args[0].n == 5

    with pytest.raises(TypeError):
        _validate(fn, [{"slug": "x", "n": "bad"}])

    with pytest.raises(TypeError):
        _validate(fn, [{"slug": "x"}])


# ---------------------------------------------------------------------------
# Fix 1 (review): pydantic path and stdlib fallback must agree on unknown
# extra keys for dataclass/TypedDict. Both silently ignore them (matching
# pydantic TypeAdapter's default, non-strict behavior for these two types —
# see the docstring on `_validate_structured` for why "forbid extras" isn't
# reliably achievable for a bare dataclass/TypedDict without mutating the
# caller's class).
# ---------------------------------------------------------------------------

def test_dataclass_extra_key_same_outcome_both_paths():
    def fn(row: Row) -> str: return row.slug

    # pydantic path (installed in this environment): extra key ignored.
    args = _validate(fn, [{"slug": "x", "n": 5, "extra": "nope"}])
    assert args[0].slug == "x"
    assert args[0].n == 5
    assert not hasattr(args[0], "extra")


def test_dataclass_extra_key_same_outcome_stdlib_path(monkeypatch):
    monkeypatch.setattr(adapters, "_has_pydantic", False)
    monkeypatch.setattr(adapters, "pydantic", None)

    def fn(row: Row) -> str: return row.slug

    args = _validate(fn, [{"slug": "x", "n": 5, "extra": "nope"}])
    assert args[0].slug == "x"
    assert args[0].n == 5
    assert not hasattr(args[0], "extra")


def test_typeddict_extra_key_same_outcome_both_paths():
    def fn(row: RowDict) -> str: return row["slug"]

    args = _validate(fn, [{"slug": "x", "n": 5, "extra": "nope"}])
    assert args[0] == {"slug": "x", "n": 5}
    assert "extra" not in args[0]


def test_typeddict_extra_key_same_outcome_stdlib_path(monkeypatch):
    monkeypatch.setattr(adapters, "_has_pydantic", False)
    monkeypatch.setattr(adapters, "pydantic", None)

    def fn(row: RowDict) -> str: return row["slug"]

    args = _validate(fn, [{"slug": "x", "n": 5, "extra": "nope"}])
    assert args[0] == {"slug": "x", "n": 5}
    assert "extra" not in args[0]


# ---------------------------------------------------------------------------
# Fix 3 (review): dict keys arrive as strings on the wire (JSON/devalue only
# produce string object keys). `Dict[K, V]` with a non-str `K` now coerces
# the string key to `K` via `K`'s own constructor before validating, so
# `Dict[int, V]` parses `{"1": 2}` -> `{1: 2}` instead of always raising.
# `Dict[str, V]` is unaffected (no coercion needed/performed).
# ---------------------------------------------------------------------------

def test_dict_int_key_coerces_string_keys():
    def fn(m: Dict[int, int]) -> int: return sum(m.values())

    args = _validate(fn, [{"1": 2, "2": 3}])
    assert args == [{1: 2, 2: 3}]
    assert all(isinstance(k, int) for k in args[0])


def test_dict_int_key_rejects_non_numeric_string():
    def fn(m: Dict[int, int]) -> int: return 0

    with pytest.raises(TypeError):
        _validate(fn, [{"not-a-number": 2}])


def test_dict_str_key_unaffected_by_coercion():
    def fn(m: Dict[str, int]) -> int: return sum(m.values())

    args = _validate(fn, [{"a": 1, "b": 2}])
    assert args == [{"a": 1, "b": 2}]


def test_stdlib_fallback_validates_dataclass(monkeypatch):
    monkeypatch.setattr(adapters, "_has_pydantic", False)
    monkeypatch.setattr(adapters, "pydantic", None)

    def fn(row: Row) -> str: return row.slug

    with pytest.raises(TypeError):
        _validate(fn, [{"slug": "x", "n": "bad"}])
    with pytest.raises(TypeError):
        _validate(fn, [{"slug": "x"}])
    args = _validate(fn, [{"slug": "x", "n": 5}])
    assert args[0].slug == "x"
    assert args[0].n == 5


def test_stdlib_fallback_validates_typeddict(monkeypatch):
    monkeypatch.setattr(adapters, "_has_pydantic", False)
    monkeypatch.setattr(adapters, "pydantic", None)

    def fn(row: RowDict) -> str: return row["slug"]

    with pytest.raises(TypeError):
        _validate(fn, [{"slug": "x", "n": "bad"}])
    args = _validate(fn, [{"slug": "x", "n": 5}])
    assert args[0] == {"slug": "x", "n": 5}


# ---------------------------------------------------------------------------
# router integration: validation failures must surface as 422, not 500
# ---------------------------------------------------------------------------

def _scaffold(tmp_path, files):
    for rel, content in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    return tmp_path


def _b64url(s: str) -> str:
    return base64.urlsafe_b64encode(s.encode("utf-8")).rstrip(b"=").decode("ascii")


def _make_environ(path: str, args: list, *, origin: str = "http://x", host: str = "x"):
    body_obj = {"payload": _b64url(devalue.stringify(args))}
    raw = json.dumps(body_obj).encode()
    return {
        "REQUEST_METHOD": "POST",
        "PATH_INFO": path,
        "CONTENT_LENGTH": str(len(raw)),
        "CONTENT_TYPE": "application/json",
        "HTTP_COOKIE": "",
        "HTTP_HOST": host,
        "HTTP_ORIGIN": origin,
        "wsgi.url_scheme": "http",
        "REMOTE_ADDR": "127.0.0.1",
        "wsgi.input": io.BytesIO(raw),
    }


def _call(environ):
    responses = []

    def sr(status, headers):
        responses.append((status, headers))

    body = b"".join(handle_remote(environ, sr))
    return responses[0], json.loads(body)


@pytest.fixture
def remote_project(tmp_path, monkeypatch):
    proj = _scaffold(tmp_path, {
        "app/__init__.py": "",
        "app/remote/__init__.py": "",
        "app/remote/nums.py": (
            "def total(xs: list[int]) -> int: return sum(xs)\n"
        ),
    })
    monkeypatch.syspath_prepend(str(proj))

    from fymo.remote.discovery import file_hash
    h = file_hash(proj / "app/remote/nums.py")
    from fymo.remote import router as router_mod
    monkeypatch.setattr(router_mod, "_resolve_module_for_hash", lambda hash_: "nums" if hash_ == h else None)

    yield proj, h
    import sys
    for name in list(sys.modules):
        if name.startswith("app."):
            del sys.modules[name]


def test_router_surfaces_element_type_violation_as_422(remote_project):
    # The WSGI status line is always "200 OK" here — fymo's remote wire
    # carries the real outcome in the JSON envelope's "status"/"type" fields,
    # not the transport status line. Validation failures must surface as a
    # 422 "validation" error envelope, not a 500 "internal" one.
    proj, h = remote_project
    env = _make_environ(f"/_fymo/remote/{h}/total", [["x", {}]])
    (status, headers), body = _call(env)
    assert status.startswith("200")
    assert body["type"] == "error"
    assert body["status"] == 422
    assert body["error"] == "validation"


def test_router_accepts_valid_list_elements(remote_project):
    proj, h = remote_project
    env = _make_environ(f"/_fymo/remote/{h}/total", [[1, 2, 3]])
    (status, headers), body = _call(env)
    assert status.startswith("200")
    assert body["type"] == "result"
    assert body["result"] is not None
