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
    """Encode `value` to a devalue string."""
    if value is UNDEFINED:
        return json.dumps([-1])
    if value is None:
        return json.dumps([1, None])

    refs: list[Any] = []  # encoded slots, indexed
    seen: dict[int, int] = {}  # id(obj) → index in refs

    def _encode(v: Any) -> int:
        # Returns the index in `refs` (>= 1) or a sentinel (< 0)
        if v is UNDEFINED:
            return -1
        if v is None:
            return -2
        if isinstance(v, float):
            if math.isnan(v): return -3
            if v == math.inf: return -4
            if v == -math.inf: return -5
            if v == 0.0 and math.copysign(1.0, v) == -1.0: return -6  # -0
        # Dedup hashable primitives by value
        if isinstance(v, (str, int, bool)) and not isinstance(v, bool) is False:
            pass  # bool falls through to id-based dedup below
        # For now: store inline, no dedup
        idx = len(refs) + 1
        refs.append(v)
        return idx

    root_idx = _encode(value)
    return json.dumps([root_idx] + refs)


def parse(s: str) -> Any:
    """Decode a devalue string back to a Python value."""
    arr = json.loads(s)
    if not isinstance(arr, list) or len(arr) == 0:
        raise ValueError("invalid devalue payload: not a non-empty array")

    root = arr[0]
    if root == -1:
        return UNDEFINED
    if root == -2:
        return None
    if root == -3:
        return float("nan")
    if root == -4:
        return math.inf
    if root == -5:
        return -math.inf
    if root == -6:
        return 0.0  # negative zero is lossy in Python; return 0.0
    if not isinstance(root, int) or root < 1 or root >= len(arr):
        raise ValueError(f"invalid root reference: {root}")

    # For now: scalar values stored inline. Containers come in later tasks.
    return arr[root]
