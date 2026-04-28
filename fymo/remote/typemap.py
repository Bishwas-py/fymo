"""Map Python types to TypeScript types."""
import dataclasses
import types
import typing
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Literal, Union, get_args, get_origin
from uuid import UUID


# Primitive map
_PRIMITIVES: dict[Any, str] = {
    str: "string",
    int: "number",
    float: "number",
    Decimal: "number",
    bool: "boolean",
    type(None): "null",
    bytes: "string",  # base64 on the wire
    datetime: "string",
    date: "string",
    UUID: "string",
}


def _is_typed_dict(py) -> bool:
    return (
        isinstance(py, type)
        and issubclass(py, dict)
        and hasattr(py, "__annotations__")
        and hasattr(py, "__required_keys__")
    )


def _is_dataclass(py) -> bool:
    return dataclasses.is_dataclass(py) and isinstance(py, type)


def _is_named_tuple(py) -> bool:
    return (
        isinstance(py, type)
        and issubclass(py, tuple)
        and hasattr(py, "_fields")
        and hasattr(py, "__annotations__")
    )


def _is_enum(py) -> bool:
    return isinstance(py, type) and issubclass(py, Enum)


def _emit_interface(name: str, fields: list[tuple[str, str, bool]], type_defs: dict[str, str]) -> str:
    """fields = [(field_name, ts_type, optional)]. Writes type_defs[name]."""
    body_lines = []
    for fname, ftype, optional in fields:
        suffix = "?" if optional else ""
        body_lines.append(f"  {fname}{suffix}: {ftype};")
    type_defs[name] = "{\n" + "\n".join(body_lines) + "\n}"
    return name


def _emit_typed_dict(py, type_defs: dict[str, str]) -> str:
    name = py.__name__
    if name in type_defs and not type_defs[name].startswith("<placeholder"):
        return name
    type_defs[name] = "<placeholder>"  # cycle guard
    fields = []
    hints = typing.get_type_hints(py)
    required = getattr(py, "__required_keys__", set(hints.keys()))
    for fname, ftype in hints.items():
        ts = python_type_to_ts(ftype, type_defs=type_defs)
        fields.append((fname, ts, fname not in required))
    return _emit_interface(name, fields, type_defs)


def _emit_dataclass_or_namedtuple(py, type_defs: dict[str, str]) -> str:
    name = py.__name__
    if name in type_defs and not type_defs[name].startswith("<placeholder"):
        return name
    type_defs[name] = "<placeholder>"
    hints = typing.get_type_hints(py)
    fields = [(fname, python_type_to_ts(ftype, type_defs=type_defs), False) for fname, ftype in hints.items()]
    return _emit_interface(name, fields, type_defs)


def _emit_enum(py, type_defs: dict[str, str]) -> str:
    name = py.__name__
    if name in type_defs:
        return name
    members = list(py)
    if all(isinstance(m.value, str) for m in members):
        rendered = " | ".join(f'"{m.value}"' for m in members)
    else:
        rendered = " | ".join(repr(m.value) for m in members)
    type_defs[name] = rendered
    return name


def python_type_to_ts(py: Any, *, type_defs: dict[str, str]) -> str:
    """Return a TypeScript type string for a Python type.

    `type_defs` is a mutable dict that accumulates side effect — when this
    function encounters a TypedDict / dataclass / pydantic model, it
    populates `type_defs[name] = "interface ..."` and returns the name.
    """
    # Direct primitive
    if py in _PRIMITIVES:
        return _PRIMITIVES[py]

    origin = get_origin(py)
    args = get_args(py)

    # list[X], set[X], frozenset[X]
    if origin in (list, set, frozenset):
        inner = python_type_to_ts(args[0], type_defs=type_defs) if args else "unknown"
        return f"{inner}[]"

    # tuple[X, Y] vs tuple[X, ...]
    if origin is tuple:
        if len(args) == 2 and args[1] is Ellipsis:
            inner = python_type_to_ts(args[0], type_defs=type_defs)
            return f"{inner}[]"
        rendered = ", ".join(python_type_to_ts(a, type_defs=type_defs) for a in args)
        return f"[{rendered}]"

    # dict[K, V]
    if origin is dict:
        k = python_type_to_ts(args[0], type_defs=type_defs) if args else "string"
        v = python_type_to_ts(args[1], type_defs=type_defs) if len(args) > 1 else "unknown"
        return f"Record<{k}, {v}>"

    # Optional[X] / Union[X, Y, ...] — handles both typing.Union and PEP 604 X | Y
    if origin is Union or isinstance(py, types.UnionType):
        parts = [python_type_to_ts(a, type_defs=type_defs) for a in args]
        # null trails for readability ("string | null" not "null | string")
        non_null = sorted(p for p in parts if p != "null")
        nulls = [p for p in parts if p == "null"]
        return " | ".join(non_null + nulls)

    # Literal[...]
    if origin is Literal:
        rendered = []
        for a in args:
            if isinstance(a, str):
                rendered.append(f'"{a}"')
            else:
                rendered.append(repr(a))
        return " | ".join(rendered)

    if _is_typed_dict(py):
        return _emit_typed_dict(py, type_defs)
    if _is_dataclass(py):
        return _emit_dataclass_or_namedtuple(py, type_defs)
    if _is_named_tuple(py):
        return _emit_dataclass_or_namedtuple(py, type_defs)
    if _is_enum(py):
        return _emit_enum(py, type_defs)

    return "unknown"
