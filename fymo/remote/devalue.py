"""Python port of devalue's tagged JSON serialization.

Wire-compatible with Rich Harris's `devalue` npm package (v5+). Used by Fymo
Remote Functions to round-trip Date/Set/undefined/repeated-refs across the
Python<->JS boundary without lossy JSON conversion.

Format:
- Sentinels at root produce bare JSON numbers: "-1" (undefined), "-3" (NaN),
  "-4" (Infinity), "-5" (-Infinity), "-6" (-0). These do NOT wrap in an array.
- All other roots produce a JSON array. Index 0 holds the encoded ROOT.
  Subsequent indices hold referenced values.
- An "encoded" value is one of:
    * a plain scalar (str/number/bool/null) — represents itself,
    * an array of integers `[i, i, ...]` — a list, each int is a slot index,
    * an object `{k: i, ...}` — a dict, each value is a slot index,
    * a tagged form like `["Date", iso]` or `["Set", i, i, ...]`.
- Cycles are encoded by self-referencing the slot index (e.g. a slot pointing
  to itself).
"""
import base64
import json
import math
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

try:
    import pydantic
    _has_pydantic = True
except ImportError:
    _has_pydantic = False


# Sentinel indices used by devalue at root (and as references inside containers).
#   -1 = undefined, -2 = null (only when referenced; null at root is `[null]`),
#   -3 = NaN, -4 = +Infinity, -5 = -Infinity, -6 = -0
class _Undefined:
    _instance = None
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    def __repr__(self):
        return "UNDEFINED"


UNDEFINED = _Undefined()


def stringify(value: Any) -> str:
    """Encode `value` to a devalue wire string."""
    # Bare-sentinel root forms (output is just the sentinel number, no array).
    if value is UNDEFINED:
        return "-1"
    if isinstance(value, float):
        if math.isnan(value): return "-3"
        if value == math.inf: return "-4"
        if value == -math.inf: return "-5"
        if value == 0.0 and math.copysign(1.0, value) == -1.0: return "-6"

    # Otherwise: array form. Slot 0 holds the encoded root.
    slots: list[Any] = [None]
    seen: dict[int, int] = {}              # id(obj) → slot, for non-primitive dedup + cycles
    scalar_seen: dict[tuple, int] = {}     # (type, value) → slot, for primitive dedup

    def _encode(v: Any) -> int:
        """Encode `v` into a slot, return the slot index (a positive integer)."""
        # Sentinel references inside containers
        if v is UNDEFINED: return -1
        if isinstance(v, float):
            if math.isnan(v): return -3
            if v == math.inf: return -4
            if v == -math.inf: return -5

        # Dedup primitives by (type, value) so [1,1,1] emits one slot
        if v is None or isinstance(v, (bool, int, str, float)):
            key = (type(v).__name__, v)
            if key in scalar_seen:
                return scalar_seen[key]
            idx = len(slots)
            slots.append(_encode_value(v, _encode))
            scalar_seen[key] = idx
            return idx

        # Dedup non-primitive identity-equal values
        if id(v) in seen:
            return seen[id(v)]

        idx = len(slots)
        slots.append(None)  # reserve cycle-safe slot
        seen[id(v)] = idx
        slots[idx] = _encode_value(v, _encode)
        return idx

    # Register the root at slot 0 BEFORE encoding so children can dedup back to it.
    if value is not None and not isinstance(value, (bool, int, str, float)):
        seen[id(value)] = 0
    elif value is None or isinstance(value, (bool, int, str, float)):
        scalar_seen[(type(value).__name__, value)] = 0
    slots[0] = _encode_value(value, _encode)
    return json.dumps(slots)


def _encode_value(v: Any, enc) -> Any:
    """Produce the encoded form for a value (scalar, structural, or tagged)."""
    # Direct scalars
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, str)):
        return v
    if isinstance(v, float):
        # NaN/Inf already handled by enc(); plain floats are scalar.
        return v

    # Tagged types
    if isinstance(v, datetime):
        return ["Date", v.isoformat()]
    if isinstance(v, date):
        return ["Date", v.isoformat()]
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, UUID):
        return str(v)
    if isinstance(v, bytes):
        return base64.b64encode(v).decode("ascii")
    if isinstance(v, Enum):
        return v.value
    if isinstance(v, (set, frozenset)):
        return ["Set"] + [enc(item) for item in v]

    # Pydantic models — flatten to dict
    if _has_pydantic and isinstance(v, pydantic.BaseModel):
        d = v.model_dump(mode="python")
        return {k: enc(val) for k, val in d.items()}

    # Containers (encode children, return structural form of indices)
    if isinstance(v, (list, tuple)):
        return [enc(item) for item in v]
    if isinstance(v, dict):
        return {k: enc(val) for k, val in v.items()}

    raise TypeError(f"devalue cannot stringify {type(v).__name__}")


def parse(s: str) -> Any:
    """Decode a devalue wire string back to a Python value."""
    parsed = json.loads(s)

    # Bare sentinel at root
    if isinstance(parsed, int) and not isinstance(parsed, bool):
        if parsed == -1: return UNDEFINED
        if parsed == -3: return float("nan")
        if parsed == -4: return math.inf
        if parsed == -5: return -math.inf
        if parsed == -6: return 0.0
        # Other bare ints aren't legal devalue; fall through.

    if not isinstance(parsed, list) or len(parsed) == 0:
        raise ValueError("invalid devalue payload")

    arr = parsed
    decoded: dict[int, Any] = {}

    def _decode(ref: Any) -> Any:
        # Sentinels referenced from a container
        if isinstance(ref, int) and not isinstance(ref, bool):
            if ref == -1: return UNDEFINED
            if ref == -2: return None  # rarely used; null is usually inline
            if ref == -3: return float("nan")
            if ref == -4: return math.inf
            if ref == -5: return -math.inf
            if ref == -6: return 0.0
            if ref < 0:
                raise ValueError(f"unknown sentinel: {ref}")
            return _decode_slot(ref)
        # A non-int ref shouldn't appear inside a structural form, but tolerate.
        return ref

    def _decode_slot(idx: int) -> Any:
        if idx in decoded:
            return decoded[idx]
        if idx < 0 or idx >= len(arr):
            raise ValueError(f"invalid slot index: {idx}")

        slot = arr[idx]

        # Tagged forms (lists with a leading string tag)
        if isinstance(slot, list) and slot and isinstance(slot[0], str):
            tag = slot[0]
            if tag == "Date":
                iso = slot[1]
                if "T" in iso:
                    value = datetime.fromisoformat(iso.replace("Z", "+00:00"))
                else:
                    value = date.fromisoformat(iso)
                decoded[idx] = value
                return value
            if tag == "Set":
                placeholder: set = set()
                decoded[idx] = placeholder
                for ref in slot[1:]:
                    placeholder.add(_decode(ref))
                return placeholder
            # Unknown tag — fall through to plain-list decoding (keeps the tag string)

        # Plain list of refs
        if isinstance(slot, list):
            out: list = []
            decoded[idx] = out
            for ref in slot:
                out.append(_decode(ref))
            return out

        # Plain dict of refs
        if isinstance(slot, dict):
            out_d: dict = {}
            decoded[idx] = out_d
            for k, ref in slot.items():
                out_d[k] = _decode(ref)
            return out_d

        # Scalar
        decoded[idx] = slot
        return slot

    return _decode_slot(0)
