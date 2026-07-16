"""Validate args coming over the wire; serialize return values back to JSON."""
import dataclasses
import inspect
import json
import typing
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


def _is_dataclass_type(t) -> bool:
    return isinstance(t, type) and dataclasses.is_dataclass(t)


def _is_namedtuple_type(t) -> bool:
    return (
        isinstance(t, type)
        and issubclass(t, tuple)
        and hasattr(t, "_fields")
        and hasattr(t, "_field_defaults")
    )


def _is_structured_type(t) -> bool:
    """dataclass / TypedDict / NamedTuple — types shaped by declared fields
    that deserve real validation instead of a pass-through dict/tuple."""
    return _is_dataclass_type(t) or typing.is_typeddict(t) or _is_namedtuple_type(t)


def _validate_structured(value: Any, hint: Any):
    """Validate a dataclass/TypedDict/NamedTuple `hint` against `value`.

    With pydantic installed, delegates to `TypeAdapter`, which fully
    validates nested structure and raises `pydantic.ValidationError` on
    mismatch (same as the existing BaseModel path — the router already maps
    that to a 422 `validation` envelope).

    Without pydantic, falls back to a best-effort stdlib structural check:
    `value` must be a dict containing every required field, and each
    present field is recursively validated against its declared type via
    `_coerce_value`. This does not replicate every typing edge case pydantic
    handles (forward refs needing extra namespace context, exotic generics),
    but it does reject the common bad shapes: missing required fields and
    wrong-typed fields.

    Unknown/extra keys: for dataclass and TypedDict targets, extra keys are
    silently ignored on BOTH paths. This matches `pydantic.TypeAdapter`'s
    *default* behavior for these two types (it has no `config=` override —
    passing `config=ConfigDict(extra="forbid")` to `TypeAdapter` raises
    `PydanticUserError` for dataclass/TypedDict, and there's no non-invasive
    way to force strict rejection without mutating the caller's class), so
    the stdlib fallback was relaxed to match rather than pydantic being
    tightened. NamedTuple is the one case where pydantic already rejects
    extra keys (it validates NamedTuple like a callable's keyword
    arguments), and the stdlib fallback mirrors that by continuing to
    reject extras there.
    """
    if _has_pydantic:
        return pydantic.TypeAdapter(hint).validate_python(value)
    return _validate_structured_stdlib(value, hint)


def _validate_structured_stdlib(value: Any, hint: Any):
    name = getattr(hint, "__name__", str(hint))
    if not isinstance(value, dict):
        raise TypeError(f"expected object/dict for {name}, got {type(value).__name__}")

    if _is_dataclass_type(hint):
        field_hints = typing.get_type_hints(hint)
        fields = {f.name: f for f in dataclasses.fields(hint)}
        kwargs = {}
        for fname, field in fields.items():
            has_default = (
                field.default is not dataclasses.MISSING
                or field.default_factory is not dataclasses.MISSING  # type: ignore[misc]
            )
            if fname not in value:
                if has_default:
                    continue
                raise TypeError(f"missing required field {fname!r} for {name}")
            kwargs[fname] = _coerce_value(value[fname], field_hints.get(fname, Any))
        # Extra keys are ignored, not rejected — matches pydantic
        # TypeAdapter's default (non-strict) behavior for dataclasses.
        return hint(**kwargs)

    if typing.is_typeddict(hint):
        ann = typing.get_type_hints(hint, include_extras=True)
        required = getattr(hint, "__required_keys__", set(ann))
        out = {}
        for fname, ftype in ann.items():
            if fname not in value:
                if fname in required:
                    raise TypeError(f"missing required key {fname!r} for {name}")
                continue
            out[fname] = _coerce_value(value[fname], ftype)
        # Extra keys are ignored, not rejected — matches pydantic
        # TypeAdapter's default (non-strict) behavior for TypedDicts.
        return out

    if _is_namedtuple_type(hint):
        ann = typing.get_type_hints(hint)
        fields = hint._fields
        defaults = getattr(hint, "_field_defaults", {})
        kwargs = {}
        for fname in fields:
            ftype = ann.get(fname, Any)
            if fname not in value:
                if fname in defaults:
                    continue
                raise TypeError(f"missing required field {fname!r} for {name}")
            kwargs[fname] = _coerce_value(value[fname], ftype)
        extra = set(value) - set(fields)
        if extra:
            raise TypeError(f"unexpected field(s) {sorted(extra)} for {name}")
        return hint(**kwargs)

    # Not a structured type we recognize — no validator available.
    return value


def _coerce_dict_key(key: Any, key_hint: Any):
    """Coerce a dict key to its declared key type before validating it.

    JSON (and devalue, which rides on top of JSON) only supports string
    object keys on the wire. Without this, a `Dict[int, V]`-typed param
    would always fail even for well-formed calls, because `{"1": 2}` can
    never satisfy "key is an int" as delivered. So when `key_hint` isn't
    `str`/`Any` and the incoming key is a string, the key is coerced via the
    hint's own constructor first (`int("1") -> 1`, `UUID("...") -> UUID`,
    `SomeEnum("member") -> SomeEnum.member`, with a dedicated true/false
    mapping for `bool` since `bool("false")` is truthy). `Dict[str, V]` is
    unaffected and remains the safe default for wire-facing dict params.
    """
    if key_hint is str or key_hint is Any:
        return _coerce_value(key, key_hint)
    if isinstance(key, str) and isinstance(key_hint, type) and key_hint is not str:
        if key_hint is bool:
            if key not in ("true", "false"):
                raise TypeError(f"cannot coerce dict key {key!r} to bool")
            key = key == "true"
        else:
            try:
                key = key_hint(key)
            except (TypeError, ValueError) as e:
                raise TypeError(
                    f"cannot coerce dict key {key!r} to {getattr(key_hint, '__name__', key_hint)}: {e}"
                )
    return _coerce_value(key, key_hint)


def _reject_undefined(value: Any) -> None:
    """devalue's UNDEFINED sentinel means "argument omitted" at a top-level
    slot (validate_args handles that before coercion) and nothing anywhere
    else. A JS call like fn([undefined]) parses to the raw sentinel nested
    in a container; letting it through guarantees a downstream 500 (no user
    code or DB driver can handle it), so every pass-through path scans for
    it before returning the value unvalidated."""
    from fymo.remote.devalue import UNDEFINED
    if value is UNDEFINED:
        raise TypeError("undefined is only valid as a whole omitted argument")
    if isinstance(value, list):
        for v in value:
            _reject_undefined(v)
    elif isinstance(value, dict):
        for v in value.values():
            _reject_undefined(v)


def _coerce_value(value: Any, hint: Any):
    """Validate `value` against `hint`. Raises TypeError or ValidationError on mismatch."""
    from fymo.remote.devalue import UNDEFINED
    if value is UNDEFINED:
        raise TypeError("undefined is only valid as a whole omitted argument")
    if hint is Any:
        _reject_undefined(value)
        return value
    if hint is type(None):
        # The NoneType branch of a union must actually check for None;
        # returning the value unchecked made `str | None` accept anything.
        if value is not None:
            raise TypeError(f"expected None, got {type(value).__name__}")
        return None
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
        args = get_args(hint)
        if not args:
            _reject_undefined(value)
            return value
        # Fixed-length tuple: tuple[int, str] validates each position against
        # its own type. tuple[int, ...] (and list/set/frozenset) validate
        # every element against the single element type.
        if origin is tuple and not (len(args) == 2 and args[-1] is Ellipsis):
            if len(value) != len(args):
                raise TypeError(f"expected {len(args)} elements, got {len(value)}")
            return [_coerce_value(v, a) for v, a in zip(value, args)]
        elem_hint = args[0]
        return [_coerce_value(v, elem_hint) for v in value]

    if origin is dict:
        if not isinstance(value, dict):
            raise TypeError(f"expected dict, got {type(value).__name__}")
        args = get_args(hint)
        if not args:
            _reject_undefined(value)
            return value
        key_hint, val_hint = args
        return {
            _coerce_dict_key(k, key_hint): _coerce_value(v, val_hint)
            for k, v in value.items()
        }

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

    # TypedDict / dataclass / NamedTuple — validated structurally: via
    # pydantic TypeAdapter when available, else a stdlib field-by-field check.
    if _is_structured_type(hint):
        return _validate_structured(value, hint)

    # Unknown/unhandled annotation — no validator available, pass through.
    _reject_undefined(value)
    return value


def validate_args(args: list, sig: inspect.Signature, hints: dict) -> list:
    """Validate and coerce positional args against the function signature.

    An omitted argument uses the parameter's default. The generated JS
    client always sends every positional slot, so a skipped trailing
    argument arrives as devalue UNDEFINED rather than being absent; both
    forms (UNDEFINED and a short args list) mean "not provided" here, which
    matches what `undefined` means at the JS call site.
    """
    from fymo.remote.devalue import UNDEFINED

    params = list(sig.parameters.values())
    if len(args) > len(params):
        raise TypeError(f"expected {len(params)} args, got {len(args)}")
    out = []
    for i, param in enumerate(params):
        arg = args[i] if i < len(args) else UNDEFINED
        if arg is UNDEFINED:
            if param.default is inspect.Parameter.empty:
                if i >= len(args):
                    raise TypeError(f"expected {len(params)} args, got {len(args)}")
                raise TypeError(f"missing required argument {param.name!r}")
            out.append(param.default)
            continue
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
