"""Map Python types to TypeScript types."""
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

    # TypedDict / dataclass / NamedTuple / pydantic.BaseModel — handled in Task 5–6
    # Enum — handled in Task 5

    return "unknown"
