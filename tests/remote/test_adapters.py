"""validate_args: pydantic validates BaseModel inputs; stdlib does isinstance checks.
serialize_response: pydantic uses model_dump; stdlib uses json with safe encoder."""
import inspect
import typing
import pytest
from datetime import datetime
from pydantic import BaseModel, Field, ValidationError
from fymo.remote.adapters import validate_args, serialize_response


def _hints_for(fn):
    return typing.get_type_hints(fn, include_extras=True)


def test_stdlib_validates_primitive_types():
    def fn(x: int, name: str) -> str: return name
    sig = inspect.signature(fn)
    hints = _hints_for(fn)

    args = validate_args([1, "alice"], sig, hints)
    assert args == [1, "alice"]


def test_stdlib_rejects_wrong_primitive():
    def fn(x: int) -> int: return x
    sig = inspect.signature(fn)
    hints = _hints_for(fn)

    with pytest.raises(TypeError, match="int"):
        validate_args(["not-an-int"], sig, hints)


def test_pydantic_validates_model_input():
    class Input(BaseModel):
        name: str = Field(min_length=1)
        body: str = Field(min_length=1)

    def fn(input: Input) -> str: return input.name
    sig = inspect.signature(fn)
    hints = _hints_for(fn)

    args = validate_args([{"name": "alice", "body": "hello"}], sig, hints)
    assert isinstance(args[0], Input)
    assert args[0].name == "alice"


def test_pydantic_raises_validation_error():
    class Input(BaseModel):
        name: str = Field(min_length=1)

    def fn(input: Input) -> str: return input.name
    sig = inspect.signature(fn)
    hints = _hints_for(fn)

    with pytest.raises(ValidationError):
        validate_args([{"name": ""}], sig, hints)


def test_serialize_pydantic_response():
    class Out(BaseModel):
        slug: str
        when: datetime

    out = Out(slug="hello", when=datetime(2026, 4, 28, 12, 0, 0))
    result = serialize_response(out, Out)
    assert result["slug"] == "hello"
    assert result["when"].startswith("2026-04-28")


def test_serialize_stdlib_response():
    from typing import TypedDict

    class Row(TypedDict):
        slug: str
        n: int

    out: Row = {"slug": "x", "n": 5}
    result = serialize_response(out, Row)
    assert result == {"slug": "x", "n": 5}


def test_arg_count_mismatch():
    def fn(a: int, b: int) -> int: return a + b
    sig = inspect.signature(fn)
    hints = _hints_for(fn)

    with pytest.raises(TypeError, match="expected 2"):
        validate_args([1], sig, hints)
