"""Map Python types to TypeScript type strings."""
from typing import Optional, Union, Literal, TypedDict, NamedTuple
from dataclasses import dataclass
from enum import Enum
from fymo.remote.typemap import python_type_to_ts


def _ts(py):
    return python_type_to_ts(py, type_defs={})


def test_primitives():
    assert _ts(str) == "string"
    assert _ts(int) == "number"
    assert _ts(float) == "number"
    assert _ts(bool) == "boolean"
    assert _ts(type(None)) == "null"
    assert _ts(bytes) == "string"  # base64 transport


def test_lists():
    assert _ts(list[str]) == "string[]"
    assert _ts(list[int]) == "number[]"
    assert _ts(list[list[bool]]) == "boolean[][]"


def test_tuples_fixed_and_variadic():
    assert _ts(tuple[int, str]) == "[number, string]"
    assert _ts(tuple[int, ...]) == "number[]"


def test_dicts():
    assert _ts(dict[str, int]) == "Record<string, number>"


def test_optional_and_union():
    assert _ts(Optional[str]) == "string | null"
    assert _ts(str | None) == "string | null"
    # Order can vary; sort union members alphabetically for determinism
    result = _ts(Union[int, str])
    assert result in ("number | string", "string | number")


def test_literal():
    assert _ts(Literal["a", "b", "c"]) == '"a" | "b" | "c"'
    assert _ts(Literal[1, 2]) == "1 | 2"


def test_set_becomes_array():
    assert _ts(set[str]) == "string[]"
    assert _ts(frozenset[int]) == "number[]"


def test_unsupported_type_returns_unknown():
    class Foo:
        pass
    assert _ts(Foo) == "unknown"


class Post(TypedDict):
    slug: str
    title: str
    count: int


@dataclass
class Comment:
    id: int
    body: str


class Color(Enum):
    RED = "red"
    BLUE = "blue"


class Pair(NamedTuple):
    a: int
    b: str


def test_typeddict_emits_interface():
    defs: dict[str, str] = {}
    name = python_type_to_ts(Post, type_defs=defs)
    assert name == "Post"
    assert "Post" in defs
    assert "slug: string" in defs["Post"]
    assert "title: string" in defs["Post"]
    assert "count: number" in defs["Post"]


def test_dataclass_emits_interface():
    defs: dict[str, str] = {}
    name = python_type_to_ts(Comment, type_defs=defs)
    assert name == "Comment"
    assert "id: number" in defs["Comment"]
    assert "body: string" in defs["Comment"]


def test_named_tuple_emits_interface():
    defs: dict[str, str] = {}
    name = python_type_to_ts(Pair, type_defs=defs)
    assert name == "Pair"
    assert "a: number" in defs["Pair"]
    assert "b: string" in defs["Pair"]


def test_string_enum_emits_union():
    defs: dict[str, str] = {}
    name = python_type_to_ts(Color, type_defs=defs)
    # Either inlined or aliased; both valid. Accept either shape.
    assert name in ("Color", '"red" | "blue"', '"blue" | "red"')
    if name == "Color":
        assert defs["Color"] in ('"red" | "blue"', '"blue" | "red"')


def test_nested_typeddict():
    class Inner(TypedDict):
        x: int

    class Outer(TypedDict):
        inner: Inner

    defs: dict[str, str] = {}
    name = python_type_to_ts(Outer, type_defs=defs)
    assert name == "Outer"
    assert "inner: Inner" in defs["Outer"]
    assert "x: number" in defs["Inner"]


def test_idempotent_re_resolution():
    """Resolving the same type twice should not duplicate the interface."""
    defs: dict[str, str] = {}
    python_type_to_ts(Post, type_defs=defs)
    python_type_to_ts(Post, type_defs=defs)
    assert list(defs.keys()).count("Post") == 1
