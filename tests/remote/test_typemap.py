"""Map Python types to TypeScript type strings."""
from typing import Optional, Union, Literal
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
