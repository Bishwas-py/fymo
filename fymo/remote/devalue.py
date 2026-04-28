"""Python port of devalue's tagged JSON serialization.

Compatible with the JS `devalue` package on the wire. Used by Fymo Remote
Functions to round-trip Date/Map/Set/BigInt/undefined/repeated-refs across
the Python<->JS boundary without lossy JSON conversion.

Format: a JSON array. Index 0 is the root reference. Subsequent indices
hold values. Tagged forms are 2-element arrays like ["Date","..."].
Negative integers are sentinels.
"""
import json
import math
from typing import Any

import base64
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID


# Sentinel values. The JS counterparts:
#   -1 → undefined,  -2 → null,  -3 → NaN,  -4 → Infinity,  -5 → -Infinity,  -6 → 0
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
    if value is UNDEFINED:
        return json.dumps([-1])

    refs: list[Any] = []          # encoded slots (1-indexed in output array)
    seen: dict[int, int] = {}     # id(obj) → index for cycle / dedup

    def _encode(v: Any) -> int:
        # Sentinels (return value < 0 means "use this sentinel directly")
        if v is UNDEFINED: return -1
        if v is None:      return -2
        if isinstance(v, float):
            if math.isnan(v): return -3
            if v == math.inf: return -4
            if v == -math.inf: return -5

        # Dedup by id
        if id(v) in seen:
            return seen[id(v)]

        # Reserve slot now (cycle-safe)
        idx = len(refs) + 1
        refs.append(None)
        seen[id(v)] = idx

        if isinstance(v, (str, int, bool)) or (isinstance(v, float) and not (math.isnan(v) or math.isinf(v))):
            refs[idx - 1] = v
            return idx

        if isinstance(v, (list, tuple)):
            refs[idx - 1] = [_encode(item) for item in v]
            return idx

        if isinstance(v, dict):
            refs[idx - 1] = {k: _encode(val) for k, val in v.items()}
            return idx

        if isinstance(v, Decimal):
            refs[idx - 1] = float(v)
            return idx

        if isinstance(v, UUID):
            refs[idx - 1] = str(v)
            return idx

        if isinstance(v, bytes):
            refs[idx - 1] = base64.b64encode(v).decode("ascii")
            return idx

        if isinstance(v, Enum):
            refs[idx - 1] = v.value
            return idx

        if isinstance(v, datetime):
            refs[idx - 1] = ["Date", v.isoformat()]
            return idx

        if isinstance(v, date):
            refs[idx - 1] = ["Date", v.isoformat()]
            return idx

        raise TypeError(f"devalue cannot stringify {type(v).__name__}")

    root_idx = _encode(value)
    return json.dumps([root_idx] + refs)


def parse(s: str) -> Any:
    arr = json.loads(s)
    if not isinstance(arr, list) or len(arr) == 0:
        raise ValueError("invalid devalue payload")

    decoded: dict[int, Any] = {}

    def _decode(idx_or_sentinel: int) -> Any:
        if idx_or_sentinel == -1: return UNDEFINED
        if idx_or_sentinel == -2: return None
        if idx_or_sentinel == -3: return float("nan")
        if idx_or_sentinel == -4: return math.inf
        if idx_or_sentinel == -5: return -math.inf
        if idx_or_sentinel == -6: return 0.0
        if idx_or_sentinel in decoded:
            return decoded[idx_or_sentinel]
        if idx_or_sentinel < 1 or idx_or_sentinel >= len(arr):
            raise ValueError(f"invalid reference: {idx_or_sentinel}")

        slot = arr[idx_or_sentinel]
        # Place a placeholder before recursing (cycle-safe for containers)
        if isinstance(slot, list) and len(slot) == 2 and slot[0] == "Date":
            iso = slot[1]
            # date.isoformat() produces "YYYY-MM-DD" (no 'T'); datetime always has 'T'.
            if "T" in iso:
                value = datetime.fromisoformat(iso.replace("Z", "+00:00"))
            else:
                value = date.fromisoformat(iso)
            decoded[idx_or_sentinel] = value
            return value
        if isinstance(slot, list):
            placeholder: list = []
            decoded[idx_or_sentinel] = placeholder
            for ref in slot:
                placeholder.append(_decode(ref))
            return placeholder
        if isinstance(slot, dict):
            placeholder_d: dict = {}
            decoded[idx_or_sentinel] = placeholder_d
            for k, ref in slot.items():
                placeholder_d[k] = _decode(ref)
            return placeholder_d
        # Scalar
        decoded[idx_or_sentinel] = slot
        return slot

    return _decode(arr[0])
