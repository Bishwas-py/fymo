"""Validate args coming over the wire; serialize return values back to JSON."""
import inspect
import json
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, get_origin, get_args, Union, Literal
from uuid import UUID

try:
    import pydantic
    _has_pydantic = True
except ImportError:
    pydantic = None  # type: ignore
    _has_pydantic = False


def _is_pydantic_model(t) -> bool:
    return _has_pydantic and isinstance(t, type) and issubclass(t, pydantic.BaseModel)


def _coerce_value(value: Any, hint: Any):
    """Validate `value` against `hint`. Raises TypeError or ValidationError on mismatch."""
    if hint is Any or hint is type(None):
        return value
    origin = get_origin(hint)

    if _is_pydantic_model(hint):
        return hint.model_validate(value)

    # Optional / Union — accept if value matches any branch
    import types
    if origin is Union or isinstance(hint, types.UnionType):
        last_err = None
        for branch in get_args(hint):
            try:
                return _coerce_value(value, branch)
            except Exception as e:
                last_err = e
        raise TypeError(f"value did not match any union branch of {hint}: {last_err}")

    if origin is Literal:
        allowed = get_args(hint)
        if value in allowed:
            return value
        raise TypeError(f"value {value!r} not in allowed literals {allowed}")

    if origin in (list, tuple, set, frozenset):
        if not isinstance(value, list):
            raise TypeError(f"expected list, got {type(value).__name__}")
        # Could recurse on element type; keep simple in v1
        return value

    if origin is dict:
        if not isinstance(value, dict):
            raise TypeError(f"expected dict, got {type(value).__name__}")
        return value

    # Concrete primitives
    if hint in (str, int, float, bool, bytes):
        if hint is bytes and isinstance(value, str):
            # bytes come over wire as base64-encoded strings
            import base64
            return base64.b64decode(value)
        if not isinstance(value, hint):
            # int allows bool subclass — exclude bool when expecting int
            if hint is int and isinstance(value, bool):
                raise TypeError(f"expected int, got bool")
            raise TypeError(f"expected {hint.__name__}, got {type(value).__name__}")
        return value

    # TypedDict / dataclass / NamedTuple — accept dicts pass-through (shallow)
    return value


def validate_args(args: list, sig: inspect.Signature, hints: dict) -> list:
    """Validate and coerce positional args against the function signature."""
    params = list(sig.parameters.values())
    if len(args) != len(params):
        raise TypeError(f"expected {len(params)} args, got {len(args)}")
    out = []
    for arg, param in zip(args, params):
        hint = hints.get(param.name, Any)
        out.append(_coerce_value(arg, hint))
    return out


def _json_encode_default(obj):
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, UUID):
        return str(obj)
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, (set, frozenset)):
        return list(obj)
    if isinstance(obj, bytes):
        import base64
        return base64.b64encode(obj).decode("ascii")
    raise TypeError(f"cannot serialize {type(obj).__name__}")


def serialize_response(value: Any, return_hint: Any) -> Any:
    """Convert a function return value to JSON-safe primitives."""
    if value is None:
        return None
    if _is_pydantic_model(type(value)):
        return value.model_dump(mode="json")
    if isinstance(value, list) and value and _has_pydantic and isinstance(value[0], pydantic.BaseModel):
        return [v.model_dump(mode="json") for v in value]
    # Roundtrip through json with safe encoder
    return json.loads(json.dumps(value, default=_json_encode_default))
