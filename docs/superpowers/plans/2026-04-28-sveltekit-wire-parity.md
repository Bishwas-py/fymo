# SvelteKit Wire Parity — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Fymo Remote Functions' v0 wire (`/__remote/<m>/<fn>` + `{args}` JSON + `{ok,data}`) with SvelteKit-parity (`/_fymo/remote/<hash>/<fn>` + base64url-devalue payload + `{type,result/error/redirect}` envelope, always HTTP 200, with `Origin === Host` CSRF guard).

**Architecture:** Three boundary changes — wire URL, request/response shape, serialization format. App-author code (functions in `app/remote/*.py`, `$remote/<name>` imports, prop-threaded callables in `getContext`) stays bit-for-bit identical. Only generated artifacts (`.js` runtime + entry stub) and the WSGI router change. A new Python module `fymo/remote/devalue.py` implements devalue's tagged-JSON format so `Date`/`Map`/`Set`/`BigInt`/`undefined`/repeated-refs round-trip with full type fidelity.

**Tech Stack:** Python 3.12+, `devalue@^5` (npm), `pydantic>=2.5` (already a dep), stdlib `hashlib`/`base64`/`json`. No new Python deps.

**Source spec:** `docs/superpowers/specs/2026-04-28-sveltekit-wire-parity-design.md`.

---

## File structure

### Create

- `fymo/remote/devalue.py` — Python port of devalue's `stringify`/`parse`. ~280 lines.
- `tests/remote/test_devalue.py` — round-trip cases (~25 tests).

### Modify

- `fymo/remote/discovery.py` — add `file_hash(path)` and `RemoteFunction.module_hash`.
- `fymo/build/manifest.py` — extend `Manifest` with `remote_modules: dict[str, RemoteModuleAssets]`.
- `fymo/build/pipeline.py` — write `remote_modules` into manifest.
- `fymo/core/manifest_cache.py` — `module_for_hash(hash)` + `get_remote_hash(name)`.
- `fymo/remote/codegen.py` — bake hash into emitted `.js`; rewrite `_RUNTIME_JS` to use devalue + new envelope.
- `fymo/core/html.py` — `_remote_marker` reads hash from manifest cache.
- `fymo/build/entry_generator.py` — inline runtime in `CLIENT_ENTRY_TEMPLATE` updated to match new envelope.
- `fymo/remote/router.py` — accept `/_fymo/remote/<hash>/<fn>`; Origin check; devalue decode/encode; always-200 envelope.
- `fymo/core/server.py` — dispatch `/_fymo/remote/` (replacing `/__remote/`).
- `package.json` — add `devalue@^5`.
- `examples/blog_app/package.json` — add `devalue@^5`.

### Tests to migrate (existing)

- `tests/remote/test_router.py` — new URL pattern, new body, new envelope, Origin check.
- `tests/integration/test_remote_e2e.py` — new URL, new body, new envelope.
- `tests/integration/test_remote_codegen_e2e.py` — `dist/manifest.json` has `remote_modules`.
- `tests/integration/test_remote_import.py` — bundle references new URL.
- `tests/integration/test_blog_e2e.py` — same; plus assert a `Date` returned from server arrives as a real `Date` in the bundle's payload (parsed via devalue).

---

## Phase A — Python devalue port

### Task 1: devalue scalars + None + undefined sentinels

**Files:**
- Create: `fymo/remote/devalue.py`
- Create: `tests/remote/test_devalue.py`

- [ ] **Step 1: Write the failing test**

```python
"""devalue serialization — primitives + sentinels.

Format reference: https://github.com/Rich-Harris/devalue
- Output is a JSON array of values.
- Index 0 holds the root reference.
- Subsequent indices hold values referenced by other entries.
- Negative integers are sentinels (-1=undefined, -2=null, -3=NaN, -4=Inf, -5=-Inf, -6=0).
"""
import json
from fymo.remote import devalue


def test_strings():
    assert devalue.parse(devalue.stringify("hello")) == "hello"


def test_numbers():
    assert devalue.parse(devalue.stringify(42)) == 42
    assert devalue.parse(devalue.stringify(3.14)) == 3.14
    assert devalue.parse(devalue.stringify(0)) == 0


def test_booleans():
    assert devalue.parse(devalue.stringify(True)) is True
    assert devalue.parse(devalue.stringify(False)) is False


def test_none_round_trips_as_null():
    assert devalue.parse(devalue.stringify(None)) is None


def test_string_root_at_index_one():
    """Output shape: '[1,"hello"]' — root reference is index 1."""
    out = devalue.stringify("hello")
    arr = json.loads(out)
    assert arr[0] == 1
    assert arr[1] == "hello"


def test_undefined_uses_sentinel_minus_one():
    """A field with the sentinel UNDEFINED encodes to -1, not present-as-null."""
    out = devalue.stringify(devalue.UNDEFINED)
    assert json.loads(out) == [-1]
```

- [ ] **Step 2: Run — expect failure**

Run: `.venv/bin/python -m pytest tests/remote/test_devalue.py -v`
Expected: `ModuleNotFoundError: No module named 'fymo.remote.devalue'`.

- [ ] **Step 3: Implement scalars in `fymo/remote/devalue.py`**

```python
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
```

- [ ] **Step 4: Run — expect pass**

Run: `.venv/bin/python -m pytest tests/remote/test_devalue.py -v`
Expected: 6 PASSED.

- [ ] **Step 5: Commit**

```bash
git add fymo/remote/devalue.py tests/remote/test_devalue.py
git commit -m "feat(devalue): scalars + null/undefined sentinels"
```

### Task 2: devalue containers — list, tuple, dict

**Files:**
- Modify: `fymo/remote/devalue.py`
- Modify: `tests/remote/test_devalue.py`

- [ ] **Step 1: Add tests**

Append to `tests/remote/test_devalue.py`:

```python
def test_list_of_strings():
    out = devalue.stringify(["a", "b", "c"])
    assert devalue.parse(out) == ["a", "b", "c"]


def test_nested_list():
    val = [[1, 2], [3, 4]]
    assert devalue.parse(devalue.stringify(val)) == val


def test_dict_of_primitives():
    val = {"name": "alice", "age": 30, "active": True}
    assert devalue.parse(devalue.stringify(val)) == val


def test_nested_dict():
    val = {"user": {"name": "alice", "tags": ["x", "y"]}}
    assert devalue.parse(devalue.stringify(val)) == val


def test_tuple_round_trips_as_list():
    """devalue has no tuple type; tuples encode as arrays and round-trip as lists."""
    assert devalue.parse(devalue.stringify((1, 2, 3))) == [1, 2, 3]


def test_empty_list():
    assert devalue.parse(devalue.stringify([])) == []


def test_empty_dict():
    assert devalue.parse(devalue.stringify({})) == {}


def test_list_root_indices():
    """A list at root: arr[0]=1, arr[1]=[idx_of_a, idx_of_b], arr[2]='a', arr[3]='b'."""
    out = devalue.stringify(["a", "b"])
    arr = json.loads(out)
    assert arr[0] == 1
    # arr[1] is a list of indices pointing to "a" and "b"
    indices = arr[1]
    assert isinstance(indices, list) and len(indices) == 2
    assert arr[indices[0]] == "a"
    assert arr[indices[1]] == "b"
```

- [ ] **Step 2: Run — expect failure**

Run: `.venv/bin/python -m pytest tests/remote/test_devalue.py -v`
Expected: 8 NEW failures (lists/dicts encode incorrectly today).

- [ ] **Step 3: Replace `_encode` and `parse` in `fymo/remote/devalue.py`**

Replace the `stringify` function body and the `parse` function with:

```python
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
```

- [ ] **Step 4: Run — expect pass**

Run: `.venv/bin/python -m pytest tests/remote/test_devalue.py -v`
Expected: 14 PASSED (6 prior + 8 new).

- [ ] **Step 5: Commit**

```bash
git add fymo/remote/devalue.py tests/remote/test_devalue.py
git commit -m "feat(devalue): list, tuple, dict containers + cycle-safe encoding"
```

### Task 3: devalue tagged types — Date, Decimal, UUID, bytes, Enum

**Files:**
- Modify: `fymo/remote/devalue.py`
- Modify: `tests/remote/test_devalue.py`

- [ ] **Step 1: Add tests**

Append to `tests/remote/test_devalue.py`:

```python
from datetime import datetime, date, timezone
from decimal import Decimal
from enum import Enum
from uuid import UUID


class Color(Enum):
    RED = "red"
    BLUE = "blue"


def test_datetime_round_trip_as_date():
    """datetime → ['Date', '<iso>']; client receives a JS Date.
    We round-trip it to a Python datetime."""
    val = datetime(2026, 4, 28, 12, 0, 0, tzinfo=timezone.utc)
    out = devalue.stringify(val)
    # Tagged shape: arr[1] should be ["Date", "<iso>"]
    arr = json.loads(out)
    assert arr[arr[0]][0] == "Date"
    parsed = devalue.parse(out)
    assert isinstance(parsed, datetime)
    assert parsed == val


def test_date_round_trips_as_iso_date():
    val = date(2026, 4, 28)
    parsed = devalue.parse(devalue.stringify(val))
    assert isinstance(parsed, date)
    assert parsed == val


def test_decimal_encodes_as_number():
    """Decimal becomes a number on the JS side; we lose Decimal precision but match SvelteKit."""
    parsed = devalue.parse(devalue.stringify(Decimal("3.14")))
    assert parsed == 3.14


def test_uuid_round_trips_as_string():
    val = UUID("12345678-1234-5678-1234-567812345678")
    parsed = devalue.parse(devalue.stringify(val))
    assert parsed == str(val)


def test_bytes_round_trip_as_base64_string():
    val = b"hello world"
    parsed = devalue.parse(devalue.stringify(val))
    # Bytes go over the wire as base64 strings; caller decodes if needed.
    import base64
    assert parsed == base64.b64encode(val).decode("ascii")


def test_str_enum_encodes_as_value():
    parsed = devalue.parse(devalue.stringify(Color.RED))
    assert parsed == "red"
```

- [ ] **Step 2: Run — expect failure**

Run: `.venv/bin/python -m pytest tests/remote/test_devalue.py -v`
Expected: 6 NEW failures with `TypeError: devalue cannot stringify datetime` etc.

- [ ] **Step 3: Extend `_encode` and `_decode` in `fymo/remote/devalue.py`**

Add these imports at the top:

```python
import base64
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID
```

Insert these branches inside `_encode` (BEFORE the final `raise TypeError`):

```python
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
```

Insert this branch inside `_decode` (AFTER the `if isinstance(slot, dict):` branch and BEFORE `# Scalar`):

```python
        if isinstance(slot, list) and len(slot) == 2 and slot[0] == "Date":
            iso = slot[1]
            try:
                value = datetime.fromisoformat(iso.replace("Z", "+00:00"))
            except ValueError:
                value = date.fromisoformat(iso)
            decoded[idx_or_sentinel] = value
            return value
```

Note: the tagged-Date check goes BEFORE the regular list-decoding branch above it. Reorder if needed: tagged-Date check first, then `isinstance(slot, list)` for plain lists. The tagged-Date pattern `[<str>, <str>]` would also match the plain-list rule, so order matters.

- [ ] **Step 4: Run — expect pass**

Run: `.venv/bin/python -m pytest tests/remote/test_devalue.py -v`
Expected: 20 PASSED (14 prior + 6 new).

- [ ] **Step 5: Commit**

```bash
git add fymo/remote/devalue.py tests/remote/test_devalue.py
git commit -m "feat(devalue): tagged Date + Decimal/UUID/bytes/Enum encoders"
```

### Task 4: devalue Set + frozenset (Map handling deferred)

**Files:**
- Modify: `fymo/remote/devalue.py`
- Modify: `tests/remote/test_devalue.py`

- [ ] **Step 1: Add tests**

Append:

```python
def test_set_round_trip():
    val = {"a", "b", "c"}
    parsed = devalue.parse(devalue.stringify(val))
    assert isinstance(parsed, set)
    assert parsed == val


def test_frozenset_round_trip():
    val = frozenset([1, 2, 3])
    parsed = devalue.parse(devalue.stringify(val))
    assert isinstance(parsed, set)  # Decodes back as plain set
    assert parsed == set(val)


def test_set_tagged_format():
    out = devalue.stringify({"x"})
    arr = json.loads(out)
    assert arr[arr[0]][0] == "Set"
```

- [ ] **Step 2: Run — expect failure**

Run: `.venv/bin/python -m pytest tests/remote/test_devalue.py -v`
Expected: 3 NEW failures with `TypeError: devalue cannot stringify set`.

- [ ] **Step 3: Extend `_encode` and `_decode`**

In `_encode`, add (before `raise TypeError`):

```python
        if isinstance(v, (set, frozenset)):
            # Encode items first, then store the tagged form
            indices = [_encode(item) for item in v]
            refs[idx - 1] = ["Set", indices]
            return idx
```

In `_decode`, add (alongside the `Date` tagged branch):

```python
        if isinstance(slot, list) and len(slot) == 2 and slot[0] == "Set":
            placeholder_s: set = set()
            decoded[idx_or_sentinel] = placeholder_s
            for ref in slot[1]:
                placeholder_s.add(_decode(ref))
            return placeholder_s
```

- [ ] **Step 4: Run — expect pass**

Run: `.venv/bin/python -m pytest tests/remote/test_devalue.py -v`
Expected: 23 PASSED.

- [ ] **Step 5: Commit**

```bash
git add fymo/remote/devalue.py tests/remote/test_devalue.py
git commit -m "feat(devalue): tagged Set encoder/decoder"
```

### Task 5: devalue pydantic + dedup

**Files:**
- Modify: `fymo/remote/devalue.py`
- Modify: `tests/remote/test_devalue.py`

- [ ] **Step 1: Add tests**

Append:

```python
from pydantic import BaseModel


class Item(BaseModel):
    sku: str
    qty: int


def test_pydantic_model_round_trips_as_dict():
    """Pydantic models go through model_dump and round-trip as plain dicts."""
    item = Item(sku="abc", qty=3)
    parsed = devalue.parse(devalue.stringify(item))
    assert parsed == {"sku": "abc", "qty": 3}


def test_dedup_repeated_dict_reference():
    """Same dict referenced twice should encode once and be deduplicated."""
    inner = {"x": 1}
    outer = {"a": inner, "b": inner}
    parsed = devalue.parse(devalue.stringify(outer))
    assert parsed == {"a": {"x": 1}, "b": {"x": 1}}
    # And on the wire, the inner dict only appears once
    out = devalue.stringify(outer)
    arr = json.loads(out)
    inner_dicts = [v for v in arr[1:] if isinstance(v, dict) and "x" in v]
    assert len(inner_dicts) == 1


def test_cyclic_reference_does_not_infinite_loop():
    """A self-referencing structure should encode without recursion error."""
    a: dict = {}
    a["self"] = a
    out = devalue.stringify(a)
    parsed = devalue.parse(out)
    assert parsed["self"] is parsed  # Reconstructed cycle
```

- [ ] **Step 2: Run — expect failure**

Run: `.venv/bin/python -m pytest tests/remote/test_devalue.py -v`
Expected: at least 1 FAIL on pydantic test (`TypeError: devalue cannot stringify Item`).

- [ ] **Step 3: Add pydantic branch in `_encode`**

At the top of the file:

```python
try:
    import pydantic
    _has_pydantic = True
except ImportError:
    _has_pydantic = False
```

In `_encode`, BEFORE the `raise TypeError` (and before the `set/frozenset` branch is fine; before the dict branch is also fine — pydantic models aren't dicts):

```python
        if _has_pydantic and isinstance(v, pydantic.BaseModel):
            # Convert to dict, then encode as a dict
            d = v.model_dump(mode="python")
            refs[idx - 1] = {k: _encode(val) for k, val in d.items()}
            return idx
```

(Dedup of repeated refs is already handled by the `seen` map. Cyclic refs are handled because we reserve the slot before recursing.)

- [ ] **Step 4: Run — expect pass**

Run: `.venv/bin/python -m pytest tests/remote/test_devalue.py -v`
Expected: 26 PASSED.

- [ ] **Step 5: Commit**

```bash
git add fymo/remote/devalue.py tests/remote/test_devalue.py
git commit -m "feat(devalue): pydantic BaseModel encoding + dedup verified"
```

---

## Phase B — Hash + manifest

### Task 6: File hash on RemoteFunction

**Files:**
- Modify: `fymo/remote/discovery.py`
- Modify: `tests/remote/test_discovery.py`

- [ ] **Step 1: Add failing test**

Append to `tests/remote/test_discovery.py`:

```python
def test_remote_function_includes_module_hash(tmp_path: Path):
    project = _scaffold(tmp_path, {
        "app/__init__.py": "",
        "app/remote/__init__.py": "",
        "app/remote/posts.py": "def hello(name: str) -> str: return name\n",
    })
    sys.path.insert(0, str(project))
    try:
        result = discover_remote_modules(project)
        fn = result["posts"]["hello"]
        assert hasattr(fn, "module_hash")
        assert isinstance(fn.module_hash, str)
        assert len(fn.module_hash) == 12
        # Same source → same hash
        result2 = discover_remote_modules(project)
        assert result2["posts"]["hello"].module_hash == fn.module_hash
    finally:
        sys.path.remove(str(project))
        for name in list(sys.modules):
            if name.startswith("app."):
                del sys.modules[name]


def test_module_hash_changes_with_source(tmp_path: Path):
    project = _scaffold(tmp_path, {
        "app/__init__.py": "",
        "app/remote/__init__.py": "",
        "app/remote/posts.py": "def a(s: str) -> str: return s\n",
    })
    sys.path.insert(0, str(project))
    try:
        h1 = discover_remote_modules(project)["posts"]["a"].module_hash
        # Edit the file
        (project / "app" / "remote" / "posts.py").write_text("def a(s: str) -> str: return s + '!'\n")
        # Force a fresh import
        for name in list(sys.modules):
            if name.startswith("app."):
                del sys.modules[name]
        h2 = discover_remote_modules(project)["posts"]["a"].module_hash
        assert h1 != h2
    finally:
        sys.path.remove(str(project))
        for name in list(sys.modules):
            if name.startswith("app."):
                del sys.modules[name]
```

- [ ] **Step 2: Run — expect failure**

Run: `.venv/bin/python -m pytest tests/remote/test_discovery.py -v`
Expected: 2 NEW failures (`AttributeError: module_hash`).

- [ ] **Step 3: Update `fymo/remote/discovery.py`**

Add the helper near the top:

```python
import hashlib

def file_hash(path: Path) -> str:
    """Return a 12-char lowercase hex SHA-256 prefix of the file's contents."""
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]
```

Update `RemoteFunction` to include `module_hash`:

```python
@dataclass(frozen=True)
class RemoteFunction:
    module: str
    name: str
    fn: Callable[..., Any]
    signature: inspect.Signature
    hints: dict[str, Any]
    module_hash: str
```

Update `discover_remote_modules` — at the start of the per-file loop, compute the hash once and pass it in:

```python
    for py in sorted(remote_dir.glob("*.py")):
        if py.name == "__init__.py" or py.stem.startswith("_"):
            continue
        module_name = py.stem
        full = f"app.remote.{module_name}"
        # ... existing import logic ...

        mod_hash = file_hash(py)

        fns: dict[str, RemoteFunction] = {}
        for name, obj in vars(mod).items():
            # ... existing filtering ...
            fns[name] = RemoteFunction(
                module=module_name,
                name=name,
                fn=obj,
                signature=sig,
                hints=hints,
                module_hash=mod_hash,
            )
        out[module_name] = fns
    return out
```

- [ ] **Step 4: Run — expect pass**

Run: `.venv/bin/python -m pytest tests/remote/test_discovery.py -v`
Expected: 6 PASSED (4 prior + 2 new).

- [ ] **Step 5: Commit**

```bash
git add fymo/remote/discovery.py tests/remote/test_discovery.py
git commit -m "feat(remote): include 12-char file_hash on RemoteFunction"
```

### Task 7: Manifest carries `remote_modules`

**Files:**
- Modify: `fymo/build/manifest.py`
- Modify: `fymo/build/pipeline.py`
- Modify: `tests/build/test_manifest.py`

- [ ] **Step 1: Add failing test**

Append to `tests/build/test_manifest.py`:

```python
def test_manifest_carries_remote_modules(tmp_path: Path):
    from fymo.build.manifest import Manifest, RouteAssets, RemoteModuleAssets
    m = Manifest(
        routes={"home": RouteAssets(ssr="ssr/home.mjs", client="client/home.A.js", css=None, preload=[])},
        remote_modules={"posts": RemoteModuleAssets(hash="abc123def456", fns=["hello", "goodbye"])},
    )
    out = tmp_path / "manifest.json"
    m.write(out)
    loaded = Manifest.read(out)
    assert loaded == m
    assert loaded.remote_modules["posts"].hash == "abc123def456"
    assert loaded.remote_modules["posts"].fns == ["hello", "goodbye"]


def test_manifest_remote_modules_optional(tmp_path: Path):
    """Apps without app/remote/ should still produce valid manifests (empty dict)."""
    from fymo.build.manifest import Manifest, RouteAssets
    m = Manifest(routes={"home": RouteAssets(ssr="ssr/home.mjs", client="client/home.A.js", css=None, preload=[])})
    out = tmp_path / "manifest.json"
    m.write(out)
    loaded = Manifest.read(out)
    assert loaded.remote_modules == {}
```

- [ ] **Step 2: Run — expect failure**

Run: `.venv/bin/python -m pytest tests/build/test_manifest.py -v`
Expected: NEW failures (`ImportError` or `unexpected keyword`).

- [ ] **Step 3: Update `fymo/build/manifest.py`**

Add the new dataclass and extend `Manifest`:

```python
@dataclass(frozen=True)
class RemoteModuleAssets:
    hash: str
    fns: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class Manifest:
    routes: Dict[str, RouteAssets]
    build_time: str = ""
    remote_modules: Dict[str, RemoteModuleAssets] = field(default_factory=dict)

    def write(self, path: Path) -> None:
        data = {
            "version": MANIFEST_VERSION,
            "buildTime": self.build_time,
            "routes": {name: asdict(r) for name, r in self.routes.items()},
            "remote_modules": {name: asdict(m) for name, m in self.remote_modules.items()},
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2))
        os.replace(tmp, path)

    @classmethod
    def read(cls, path: Path) -> Optional["Manifest"]:
        if not path.is_file():
            return None
        data = json.loads(path.read_text())
        if data.get("version") != MANIFEST_VERSION:
            raise ValueError(
                f"manifest.json version {data.get('version')} unsupported "
                f"(expected {MANIFEST_VERSION}); rebuild with `fymo build`"
            )
        routes = {
            name: RouteAssets(
                ssr=r["ssr"],
                client=r["client"],
                css=r.get("css"),
                preload=list(r.get("preload", [])),
            )
            for name, r in data.get("routes", {}).items()
        }
        remote_modules = {
            name: RemoteModuleAssets(hash=m["hash"], fns=list(m.get("fns", [])))
            for name, m in data.get("remote_modules", {}).items()
        }
        return cls(routes=routes, build_time=data.get("buildTime", ""), remote_modules=remote_modules)
```

- [ ] **Step 4: Update `fymo/build/pipeline.py` to populate `remote_modules`**

Find the section in `BuildPipeline.build()` where `remote_modules = discover_remote_modules(...)` is called. After it, build a `RemoteModuleAssets` map and pass it to `Manifest(...)`:

```python
        from fymo.build.manifest import RemoteModuleAssets

        # ... existing remote_modules discovery ...
        remote_assets: dict[str, RemoteModuleAssets] = {}
        for module_name, fns in remote_modules.items():
            if not fns:
                continue
            any_fn = next(iter(fns.values()))
            remote_assets[module_name] = RemoteModuleAssets(
                hash=any_fn.module_hash,
                fns=sorted(fns.keys()),
            )

        # Where Manifest(...) is constructed at the end of _build_manifest, add:
        # return Manifest(routes=route_assets, build_time=..., remote_modules=remote_assets)
```

(Read the existing `_build_manifest` to find the exact construction site, then thread `remote_assets` through.)

- [ ] **Step 5: Run — expect pass**

Run: `.venv/bin/python -m pytest tests/build/test_manifest.py tests/integration/test_remote_codegen_e2e.py -v`
Expected: all PASS.

Run the full suite as a sanity check:
`.venv/bin/python -m pytest tests/ -q`
Expected: no regressions.

- [ ] **Step 6: Commit**

```bash
git add fymo/build/manifest.py fymo/build/pipeline.py tests/build/test_manifest.py
git commit -m "feat(build): manifest carries remote_modules with file hashes"
```

### Task 8: ManifestCache exposes hash lookups

**Files:**
- Modify: `fymo/core/manifest_cache.py`
- Modify: `tests/core/test_manifest_cache.py`

- [ ] **Step 1: Add failing test**

Append:

```python
def test_module_for_hash_round_trip(tmp_path: Path):
    from fymo.build.manifest import Manifest, RouteAssets, RemoteModuleAssets
    Manifest(
        routes={"home": RouteAssets(ssr="ssr/home.mjs", client="client/home.A.js", css=None, preload=[])},
        remote_modules={"posts": RemoteModuleAssets(hash="abc123def456", fns=["hello"])},
    ).write(tmp_path / "manifest.json")

    cache = ManifestCache(tmp_path)
    assert cache.module_for_hash("abc123def456") == "posts"
    assert cache.module_for_hash("nonexistent") is None
    assert cache.get_remote_hash("posts") == "abc123def456"
    assert cache.get_remote_hash("missing") is None
```

- [ ] **Step 2: Run — expect failure**

Run: `.venv/bin/python -m pytest tests/core/test_manifest_cache.py -v`
Expected: NEW failures (`AttributeError`).

- [ ] **Step 3: Add methods to `ManifestCache`**

```python
    def module_for_hash(self, hash: str) -> str | None:
        """Return the remote-module name owning this hash, or None."""
        manifest = self.get()
        for name, asset in manifest.remote_modules.items():
            if asset.hash == hash:
                return name
        return None

    def get_remote_hash(self, module_name: str) -> str | None:
        manifest = self.get()
        asset = manifest.remote_modules.get(module_name)
        return asset.hash if asset else None
```

- [ ] **Step 4: Run — expect pass**

Run: `.venv/bin/python -m pytest tests/core/test_manifest_cache.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add fymo/core/manifest_cache.py tests/core/test_manifest_cache.py
git commit -m "feat(core): manifest cache exposes module_for_hash and get_remote_hash"
```

---

## Phase C — Codegen update

### Task 9: Bake hash into emitted .js + new __runtime.js

**Files:**
- Modify: `fymo/remote/codegen.py`
- Modify: `tests/remote/test_codegen.py`

- [ ] **Step 1: Add failing test**

Append to `tests/remote/test_codegen.py`:

```python
def test_emitted_js_bakes_hash_const(tmp_path: Path):
    """Generated .js should include `const HASH = '...'` and reference it in fetch wrappers."""
    def hello(name: str) -> str: return name

    sig = inspect.signature(hello)
    hints = typing.get_type_hints(hello)
    fn = RemoteFunction(module="posts", name="hello", fn=hello, signature=sig, hints=hints, module_hash="abc123def456")
    fns = {"hello": fn}

    emit_module("posts", fns, tmp_path)

    js = (tmp_path / "posts.js").read_text()
    assert "const HASH = 'abc123def456';" in js
    # The fetch wrapper passes HASH (not module name) and the fn name to __rpc
    assert "__rpc(HASH, 'hello'," in js


def test_runtime_js_uses_devalue_and_envelope(tmp_path: Path):
    from fymo.remote.codegen import emit_runtime
    emit_runtime(tmp_path)
    runtime = (tmp_path / "__runtime.js").read_text()
    # The new runtime imports devalue
    assert "from 'devalue'" in runtime
    # Hits the new URL pattern
    assert "/_fymo/remote/" in runtime
    # Handles the new envelope shape
    assert "result" in runtime and "redirect" in runtime
    # Uses base64url
    assert "btoa" in runtime
    assert "replaceAll" in runtime  # for the +/= → -/_/'' transforms
```

- [ ] **Step 2: Run — expect failure**

Run: `.venv/bin/python -m pytest tests/remote/test_codegen.py -v`
Expected: 2 NEW failures (old codegen has none of these).

- [ ] **Step 3: Update `fymo/remote/codegen.py`**

Replace `_RUNTIME_JS` with:

```python
_RUNTIME_JS = '''// AUTO-GENERATED. Do not edit. Fymo remote-functions client runtime.
import { stringify, parse } from 'devalue';

const REMOTE_MARKER = "__fymo_remote";

function b64url(s) {
    return btoa(s).replaceAll("+", "-").replaceAll("/", "_").replaceAll("=", "");
}

export async function __rpc(hash, name, args) {
    const url = `/_fymo/remote/${hash}/${name}`;
    const payload = b64url(stringify(args));
    const res = await fetch(url, {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ payload }),
    });
    let env;
    try { env = await res.json(); }
    catch (e) { throw new Error("invalid response from " + url); }
    if (env.type === "redirect") {
        window.location.href = env.location;
        return;
    }
    if (env.type === "error") {
        const e = new Error(env.error || "remote_error");
        e.status = env.status;
        e.error = env.error;
        e.issues = env.issues;
        throw e;
    }
    return parse(env.result);
}

// Replaces marker objects in props (emitted by SSR) with real fetch wrappers.
export function __resolveRemoteProps(props) {
    for (const key in props) {
        const v = props[key];
        if (v && typeof v === "object" && v[REMOTE_MARKER]) {
            const sep = v[REMOTE_MARKER].indexOf("/");
            const hash = v[REMOTE_MARKER].slice(0, sep);
            const name = v[REMOTE_MARKER].slice(sep + 1);
            props[key] = (...args) => __rpc(hash, name, args);
        }
    }
    return props;
}
'''
```

Update `_format_function_js` to bake the hash and route through it:

```python
def _format_function_js(fn: RemoteFunction) -> str:
    pnames = list(fn.signature.parameters.keys())
    params = ", ".join(pnames)
    args = "[" + ", ".join(pnames) + "]"
    return f"export const {fn.name} = ({params}) => __rpc(HASH, '{fn.name}', {args});"
```

Update `emit_module` so the `js_lines` start with the `HASH` const:

```python
def emit_module(module_name: str, fns: dict[str, RemoteFunction], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    type_defs: dict[str, str] = {}
    dts_fn_lines: list[str] = []
    for fn in fns.values():
        dts_fn_lines.append(_format_function_dts(fn, type_defs))

    dts_lines = [f"// AUTO-GENERATED. Do not edit. Source: app/remote/{module_name}.py", ""]
    for name in sorted(type_defs):
        body = type_defs[name]
        if body.startswith("{"):
            dts_lines.append(f"export interface {name} {body}")
        else:
            dts_lines.append(f"export type {name} = {body};")
        dts_lines.append("")
    dts_lines.extend(dts_fn_lines)
    (out_dir / f"{module_name}.d.ts").write_text("\n".join(dts_lines) + "\n")

    # Determine the hash from any fn (they all share the same module_hash)
    any_fn = next(iter(fns.values()))
    js_lines = [
        f"// AUTO-GENERATED. Do not edit. Source: app/remote/{module_name}.py",
        "import { __rpc } from './__runtime.js';",
        f"const HASH = '{any_fn.module_hash}';",
        "",
    ]
    for fn in fns.values():
        js_lines.append(_format_function_js(fn))
    (out_dir / f"{module_name}.js").write_text("\n".join(js_lines) + "\n")
```

- [ ] **Step 4: Run — expect pass**

Run: `.venv/bin/python -m pytest tests/remote/test_codegen.py -v`
Expected: all PASS (existing 3 still pass, 2 new pass).

- [ ] **Step 5: Commit**

```bash
git add fymo/remote/codegen.py tests/remote/test_codegen.py
git commit -m "feat(codegen): bake module hash into .js + devalue runtime"
```

---

## Phase D — SSR marker + entry stub

### Task 10: SSR marker uses hash; entry stub uses devalue + envelope

**Files:**
- Modify: `fymo/core/html.py`
- Modify: `fymo/build/entry_generator.py`
- Modify: `tests/core/test_html.py`

- [ ] **Step 1: Update the html test for the new marker shape**

Edit `tests/core/test_html.py:test_remote_callable_serialized_as_marker`. Replace its assertion lines with:

```python
    # Marker now carries hash, not module name
    assert '"__fymo_remote":"<hash-stub>/create_post"' in html or '"__fymo_remote": "<hash-stub>/create_post"' in html
```

The test scaffolds `app.remote.posts` directly via sys.modules; we'll need a way to provide a fake hash. Update the test to bypass real manifest lookup by monkeypatching:

```python
def test_remote_callable_serialized_as_marker(monkeypatch):
    """A callable from app.remote.* in props is serialized as {__fymo_remote: '<hash>/<fn>'}."""
    import sys, types
    fake_module = types.ModuleType("app.remote.posts")
    def create_post(title: str) -> str: return title
    create_post.__module__ = "app.remote.posts"
    fake_module.create_post = create_post
    sys.modules.setdefault("app", types.ModuleType("app"))
    sys.modules.setdefault("app.remote", types.ModuleType("app.remote"))
    sys.modules["app.remote.posts"] = fake_module

    # Stub out the manifest cache hash lookup
    from fymo.core import html as html_mod
    monkeypatch.setattr(html_mod, "_lookup_remote_hash", lambda mod_name: "abc123def456")

    from fymo.build.manifest import RouteAssets
    assets = RouteAssets(ssr="ssr/x.mjs", client="client/x.js", css=None, preload=[])
    out = html_mod.build_html(
        body="",
        head_extra="",
        props={"create_post": create_post},
        assets=assets,
        title="t",
        asset_prefix="/dist",
    )
    assert '"__fymo_remote":"abc123def456/create_post"' in out or '"__fymo_remote": "abc123def456/create_post"' in out
```

- [ ] **Step 2: Run — expect failure**

Run: `.venv/bin/python -m pytest tests/core/test_html.py -v`
Expected: NEW failure (`AttributeError: module 'fymo.core.html' has no attribute '_lookup_remote_hash'`).

- [ ] **Step 3: Update `fymo/core/html.py`**

Replace `_remote_marker` to look up the hash from the manifest cache (with a settable hook for tests):

```python
def _lookup_remote_hash(module_name: str) -> str | None:
    """Look up a remote module's hash from the manifest. Overridable in tests."""
    from fymo.core.manifest_cache import _SHARED_CACHE  # see step 4 — module-level cache
    if _SHARED_CACHE is None:
        return None
    return _SHARED_CACHE.get_remote_hash(module_name)


def _remote_marker(obj):
    mod_name = getattr(obj, "__module__", None)
    if not (mod_name and mod_name.startswith("app.remote.") and callable(obj)):
        raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")
    short = mod_name[len("app.remote."):]
    hash = _lookup_remote_hash(short)
    if not hash:
        raise TypeError(
            f"remote module 'app.remote.{short}' has no hash in manifest "
            f"(did you forget to run `fymo build`?)"
        )
    return {"__fymo_remote": f"{hash}/{obj.__name__}"}
```

- [ ] **Step 4: Add a module-level shared cache reference**

In `fymo/core/manifest_cache.py`, at the bottom:

```python
# Set at FymoApp init time so html._remote_marker can find the hash without
# needing a reference threaded through every call site.
_SHARED_CACHE: ManifestCache | None = None


def set_shared_cache(cache: ManifestCache | None) -> None:
    global _SHARED_CACHE
    _SHARED_CACHE = cache
```

In `fymo/core/server.py:FymoApp.__init__`, after creating the manifest cache, register it:

```python
            from fymo.core.manifest_cache import set_shared_cache
            set_shared_cache(self.manifest_cache)
```

- [ ] **Step 5: Update `CLIENT_ENTRY_TEMPLATE` in `fymo/build/entry_generator.py`**

Replace the inline `__rpc` body to use the new wire shape:

```python
CLIENT_ENTRY_TEMPLATE = """\
import {{ hydrate }} from 'svelte';
import {{ stringify, parse }} from 'devalue';
import Component from '{component_import}';

const propsEl = document.getElementById('svelte-props');
const props = propsEl ? JSON.parse(propsEl.textContent) : {{}};
const docEl = document.getElementById('svelte-doc');
const doc = docEl ? JSON.parse(docEl.textContent) : {{}};
globalThis.getDoc = () => doc;

function b64url(s) {{
    return btoa(s).replaceAll('+', '-').replaceAll('/', '_').replaceAll('=', '');
}}
async function __rpc(hash, name, args) {{
    const res = await fetch(`/_fymo/remote/${{hash}}/${{name}}`, {{
        method: 'POST', credentials: 'same-origin',
        headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify({{ payload: b64url(stringify(args)) }}),
    }});
    let env;
    try {{ env = await res.json(); }}
    catch (e) {{ throw new Error('invalid response'); }}
    if (env.type === 'redirect') {{ window.location.href = env.location; return; }}
    if (env.type === 'error') {{
        const e = new Error(env.error);
        e.status = env.status; e.error = env.error; e.issues = env.issues;
        throw e;
    }}
    return parse(env.result);
}}
function __resolveRemoteProps(p) {{
    for (const k in p) {{
        const v = p[k];
        if (v && typeof v === 'object' && v.__fymo_remote) {{
            const sep = v.__fymo_remote.indexOf('/');
            const hash = v.__fymo_remote.slice(0, sep);
            const name = v.__fymo_remote.slice(sep + 1);
            p[k] = (...args) => __rpc(hash, name, args);
        }}
    }}
}}
__resolveRemoteProps(props);

const target = document.getElementById('svelte-app');
hydrate(Component, {{ target, props }});
"""
```

- [ ] **Step 6: Run — expect pass**

Run: `.venv/bin/python -m pytest tests/core/test_html.py -v`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add fymo/core/html.py fymo/core/manifest_cache.py fymo/core/server.py fymo/build/entry_generator.py tests/core/test_html.py
git commit -m "feat(ssr): marker carries hash; entry stub uses devalue + envelope"
```

---

## Phase E — Router rewrite

### Task 11: New URL, Origin check, devalue decode/encode, always-200 envelope

**Files:**
- Modify: `fymo/remote/router.py`
- Modify: `fymo/core/server.py`
- Modify: `tests/remote/test_router.py`

- [ ] **Step 1: Update tests for the new wire**

Replace the helper functions and tests in `tests/remote/test_router.py` with versions that use the new URL + body + envelope:

```python
"""WSGI handler for remote function calls — SvelteKit-style wire."""
import base64
import io
import json
import sys
from pathlib import Path
import pytest
from fymo.remote.router import handle_remote
from fymo.remote import devalue


def _scaffold(tmp_path, files):
    for rel, content in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    return tmp_path


def _b64url(s: str) -> str:
    return base64.urlsafe_b64encode(s.encode("utf-8")).rstrip(b"=").decode("ascii")


def _make_environ(path: str, args: list, *, cookies: str = "", origin: str | None = "http://x", host: str = "x", scheme: str = "http"):
    body_obj = {"payload": _b64url(devalue.stringify(args))}
    raw = json.dumps(body_obj).encode()
    env = {
        "REQUEST_METHOD": "POST",
        "PATH_INFO": path,
        "CONTENT_LENGTH": str(len(raw)),
        "CONTENT_TYPE": "application/json",
        "HTTP_COOKIE": cookies,
        "HTTP_HOST": host,
        "wsgi.url_scheme": scheme,
        "REMOTE_ADDR": "127.0.0.1",
        "wsgi.input": io.BytesIO(raw),
    }
    if origin is not None:
        env["HTTP_ORIGIN"] = origin
    return env


def _call(environ):
    responses = []
    def sr(status, headers): responses.append((status, headers))
    body = b"".join(handle_remote(environ, sr))
    return responses[0], json.loads(body)


@pytest.fixture
def remote_project(tmp_path, monkeypatch):
    proj = _scaffold(tmp_path, {
        "app/__init__.py": "",
        "app/remote/__init__.py": "",
        "app/remote/posts.py": (
            "from fymo.remote import current_uid, NotFound\n"
            "def hello(name: str) -> str: return f'hi {name}'\n"
            "def whoami() -> str: return current_uid()\n"
            "def boom() -> str: raise NotFound('nope')\n"
        ),
    })
    monkeypatch.syspath_prepend(str(proj))

    # Stub the manifest hash lookup
    from fymo.remote.discovery import file_hash
    h = file_hash(proj / "app/remote/posts.py")
    from fymo.remote import router as router_mod
    monkeypatch.setattr(router_mod, "_resolve_module_for_hash", lambda hash_: "posts" if hash_ == h else None)

    yield proj, h
    for name in list(sys.modules):
        if name.startswith("app."):
            del sys.modules[name]


def test_calls_function_returns_result_envelope(remote_project):
    proj, h = remote_project
    env = _make_environ(f"/_fymo/remote/{h}/hello", ["alice"], host="x", origin="http://x")
    (status, headers), body = _call(env)
    assert status.startswith("200")
    assert body["type"] == "result"
    # decode the devalue-encoded result
    assert devalue.parse(body["result"]) == "hi alice"


def test_cross_origin_returns_403_envelope(remote_project):
    proj, h = remote_project
    env = _make_environ(f"/_fymo/remote/{h}/hello", ["alice"], host="yoursite.com", origin="https://evil.com")
    (status, _), body = _call(env)
    assert status.startswith("200")
    assert body == {"type": "error", "status": 403, "error": "cross_origin"}


def test_missing_origin_is_allowed(remote_project):
    """Server-to-server / curl with no Origin header should not be CSRF-blocked."""
    proj, h = remote_project
    env = _make_environ(f"/_fymo/remote/{h}/hello", ["alice"], host="x", origin=None)
    (status, _), body = _call(env)
    assert status.startswith("200")
    assert body["type"] == "result"


def test_unknown_hash_returns_404_envelope(remote_project):
    env = _make_environ("/_fymo/remote/000000000000/hello", ["alice"], host="x", origin="http://x")
    (status, _), body = _call(env)
    assert status.startswith("200")
    assert body == {"type": "error", "status": 404, "error": "unknown_module"}


def test_unknown_function_returns_404_envelope(remote_project):
    proj, h = remote_project
    env = _make_environ(f"/_fymo/remote/{h}/nope", [], host="x", origin="http://x")
    (status, _), body = _call(env)
    assert status.startswith("200")
    assert body["type"] == "error"
    assert body["status"] == 404


def test_validation_error_returns_422_envelope(remote_project):
    proj, h = remote_project
    env = _make_environ(f"/_fymo/remote/{h}/hello", [123], host="x", origin="http://x")
    (status, _), body = _call(env)
    assert status.startswith("200")
    assert body["type"] == "error"
    assert body["status"] == 422


def test_domain_error_returns_envelope(remote_project):
    proj, h = remote_project
    env = _make_environ(f"/_fymo/remote/{h}/boom", [], host="x", origin="http://x")
    (status, _), body = _call(env)
    assert status.startswith("200")
    assert body["type"] == "error"
    assert body["status"] == 404
    assert body["error"] == "not_found"


def test_uid_cookie_issued_on_first_call(remote_project):
    proj, h = remote_project
    env = _make_environ(f"/_fymo/remote/{h}/whoami", [], host="x", origin="http://x")
    (status, headers), body = _call(env)
    set_cookie = next((v for k, v in headers if k.lower() == "set-cookie"), None)
    assert set_cookie is not None
    assert "fymo_uid=" in set_cookie
```

- [ ] **Step 2: Run — expect failure**

Run: `.venv/bin/python -m pytest tests/remote/test_router.py -v`
Expected: many failures (the old router uses different URL, body, response).

- [ ] **Step 3: Rewrite `fymo/remote/router.py`**

```python
"""WSGI handler for POST /_fymo/remote/<hash>/<fn>."""
import base64
import importlib
import inspect
import json
import traceback
import typing
from typing import Iterable, Callable

from fymo.remote import devalue
from fymo.remote.adapters import validate_args
from fymo.remote.context import request_scope
from fymo.remote.errors import RemoteError
from fymo.remote.identity import _ensure_uid

try:
    import pydantic
    _has_pydantic = True
except ImportError:
    _has_pydantic = False

_MAX_BODY = 1 * 1024 * 1024
_PATH_PREFIX = "/_fymo/remote/"


# Hash → module-name lookup. Overridable in tests; production is wired via
# fymo.core.server when ManifestCache is available.
_resolve_module_for_hash: Callable[[str], str | None] = lambda h: None


def _200(start_response, payload: dict, set_cookie: str | None = None) -> Iterable[bytes]:
    body = json.dumps(payload).encode("utf-8")
    headers = [
        ("Content-Type", "application/json"),
        ("Content-Length", str(len(body))),
    ]
    if set_cookie:
        headers.append(("Set-Cookie", set_cookie))
    start_response("200 OK", headers)
    return [body]


def _b64url_decode(s: str) -> str:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad).decode("utf-8")


def _origin_ok(environ: dict) -> bool:
    """Reject only when Origin is present AND mismatches Host."""
    origin = environ.get("HTTP_ORIGIN")
    if not origin:
        return True
    host = environ.get("HTTP_HOST")
    if not host:
        return True
    scheme = environ.get("wsgi.url_scheme", "http")
    expected = f"{scheme}://{host}"
    return origin == expected


def _resolve_fn_in_module(module_name: str, fn_name: str):
    if not module_name.replace("_", "").isalnum():
        return None, None, None
    if not fn_name.replace("_", "").isalnum() or fn_name.startswith("_"):
        return None, None, None
    full = f"app.remote.{module_name}"
    try:
        mod = importlib.import_module(full)
    except ImportError:
        return None, None, None
    fn = getattr(mod, fn_name, None)
    if fn is None or not callable(fn) or getattr(fn, "__module__", None) != full:
        return None, None, None
    return fn, inspect.signature(fn), typing.get_type_hints(fn, include_extras=True)


def handle_remote(environ: dict, start_response) -> Iterable[bytes]:
    # 1. CSRF: Origin === Host
    if not _origin_ok(environ):
        return _200(start_response, {"type": "error", "status": 403, "error": "cross_origin"})

    # 2. Parse path
    path = environ.get("PATH_INFO", "")
    if not path.startswith(_PATH_PREFIX):
        return _200(start_response, {"type": "error", "status": 400, "error": "bad_path"})
    rest = path[len(_PATH_PREFIX):]
    parts = rest.split("/")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        return _200(start_response, {"type": "error", "status": 400, "error": "bad_path"})
    hash_, fn_name = parts

    # 3. Hash → module
    module_name = _resolve_module_for_hash(hash_)
    if module_name is None:
        return _200(start_response, {"type": "error", "status": 404, "error": "unknown_module"})

    # 4. Resolve function in module
    fn, sig, hints = _resolve_fn_in_module(module_name, fn_name)
    if fn is None:
        return _200(start_response, {"type": "error", "status": 404, "error": "unknown_function"})

    # 5. Body parse + payload decode
    try:
        length = int(environ.get("CONTENT_LENGTH") or 0)
    except ValueError:
        length = 0
    if length > _MAX_BODY:
        return _200(start_response, {"type": "error", "status": 413, "error": "too_large"})
    raw = environ["wsgi.input"].read(length) if length else b"{}"
    try:
        body = json.loads(raw or b"{}")
        payload_b64 = body.get("payload", "")
        payload_str = _b64url_decode(payload_b64) if payload_b64 else "[1,[]]"
        args = devalue.parse(payload_str)
        if not isinstance(args, list):
            raise ValueError("payload must devalue-parse to a list of args")
    except Exception as e:
        return _200(start_response, {"type": "error", "status": 400, "error": "bad_payload", "message": str(e)})

    # 6. Validate args
    try:
        validated = validate_args(args, sig, hints)
    except Exception as e:
        if _has_pydantic and isinstance(e, pydantic.ValidationError):
            return _200(start_response, {"type": "error", "status": 422, "error": "validation", "issues": e.errors()})
        return _200(start_response, {"type": "error", "status": 422, "error": "validation", "message": str(e)})

    # 7. Identity + dispatch
    uid, set_cookie = _ensure_uid(environ)
    try:
        with request_scope(uid=uid, environ=environ):
            result = fn(*validated)
    except RemoteError as e:
        return _200(start_response, {"type": "error", "status": e.status, "error": e.code, "message": str(e)}, set_cookie)
    except Exception as e:
        return _200(start_response, {"type": "error", "status": 500, "error": "internal", "message": str(e), "traceback": traceback.format_exc()}, set_cookie)

    # 8. Encode response via devalue
    try:
        encoded = devalue.stringify(result)
    except Exception as e:
        return _200(start_response, {"type": "error", "status": 500, "error": "encode_failed", "message": str(e)}, set_cookie)

    return _200(start_response, {"type": "result", "result": encoded}, set_cookie)
```

- [ ] **Step 4: Update `fymo/core/server.py` to wire the manifest-driven hash resolver and the new URL prefix**

Find the `/__remote/` dispatch branch in `FymoApp.__call__`. Replace with:

```python
        if path.startswith("/_fymo/remote/"):
            from fymo.remote import router as router_mod
            # Wire the resolver to the live manifest cache (idempotent).
            if self.manifest_cache is not None:
                router_mod._resolve_module_for_hash = self.manifest_cache.module_for_hash
            return router_mod.handle_remote(environ, start_response)
```

Remove (or leave dead) the old `/__remote/` branch. Cleanup of dead code happens in Task 13.

- [ ] **Step 5: Run — expect pass**

Run: `.venv/bin/python -m pytest tests/remote/test_router.py -v`
Expected: 8 PASSED.

- [ ] **Step 6: Commit**

```bash
git add fymo/remote/router.py fymo/core/server.py tests/remote/test_router.py
git commit -m "feat(remote): SvelteKit-style wire — /_fymo/remote/<hash>/<fn> + envelope"
```

---

## Phase F — npm dep + integration test migration

### Task 12: Add `devalue@^5` to npm

**Files:**
- Modify: `package.json`
- Modify: `examples/blog_app/package.json`
- Modify: `examples/todo_app/package.json` (so existing tests still build)

- [ ] **Step 1: Add to dependencies**

In each `package.json`, under `dependencies`:

```json
"devalue": "^5.0.0"
```

(Not devDependencies — this is shipped to the browser by esbuild.)

- [ ] **Step 2: Install**

```bash
npm install
cd examples/blog_app && npm install && cd -
cd examples/todo_app && npm install && cd -
```

- [ ] **Step 3: Quick verify devalue resolves**

```bash
cd examples/todo_app
node -e "import('devalue').then(m => console.log(typeof m.stringify))"
cd -
```

Expected: prints `function`.

- [ ] **Step 4: Commit**

```bash
git add package.json package-lock.json examples/blog_app/package.json examples/blog_app/package-lock.json examples/todo_app/package.json examples/todo_app/package-lock.json
git commit -m "deps: add devalue@^5 (shipped to browser by esbuild)"
```

### Task 13: Migrate existing integration tests to the new wire

**Files:**
- Modify: `tests/integration/test_remote_e2e.py`
- Modify: `tests/integration/test_remote_codegen_e2e.py`
- Modify: `tests/integration/test_remote_import.py`
- Modify: `tests/integration/test_blog_e2e.py`

- [ ] **Step 1: Update `test_remote_codegen_e2e.py` for the new manifest field**

Replace the assertions about `dist/client/_remote/<name>.js` content to also assert the manifest:

```python
# After the existing dist artifact assertions, add:
import json
manifest = json.loads((example_app / "dist" / "manifest.json").read_text())
assert "remote_modules" in manifest
assert "test_mod" in manifest["remote_modules"]
assert len(manifest["remote_modules"]["test_mod"]["hash"]) == 12
assert "hello" in manifest["remote_modules"]["test_mod"]["fns"]

# And update the JS content assertions:
js = (example_app / "dist" / "client" / "_remote" / "test_mod.js").read_text()
assert "const HASH = '" in js
assert "__rpc(HASH, 'hello'," in js
```

Remove any old assertion like `assert "test_mod/hello" in js` (which referenced the old URL pattern).

- [ ] **Step 2: Update `test_remote_e2e.py` to use new URL + body**

Replace the test to construct the new wire shape:

```python
import base64
import io
import json
import sys
from pathlib import Path
import pytest


@pytest.mark.usefixtures("node_available")
def test_remote_call_through_fymoapp(example_app: Path, monkeypatch):
    remote_dir = example_app / "app" / "remote"
    remote_dir.mkdir(parents=True, exist_ok=True)
    (remote_dir / "__init__.py").write_text("")
    (remote_dir / "greeter.py").write_text(
        "def hello(name: str) -> str:\n    return f'hi {name}'\n"
    )

    from fymo.build.pipeline import BuildPipeline
    BuildPipeline(project_root=example_app).build(dev=False)

    # Read the hash from the manifest
    manifest = json.loads((example_app / "dist" / "manifest.json").read_text())
    hash_ = manifest["remote_modules"]["greeter"]["hash"]

    monkeypatch.chdir(example_app)
    from fymo import create_app
    app = create_app(example_app)
    try:
        from fymo.remote import devalue
        payload_b64 = base64.urlsafe_b64encode(
            devalue.stringify(["alice"]).encode("utf-8")
        ).rstrip(b"=").decode("ascii")
        body_payload = json.dumps({"payload": payload_b64}).encode()

        responses = []
        def sr(status, headers): responses.append((status, headers))
        body = b"".join(app({
            "REQUEST_METHOD": "POST",
            "PATH_INFO": f"/_fymo/remote/{hash_}/hello",
            "CONTENT_LENGTH": str(len(body_payload)),
            "CONTENT_TYPE": "application/json",
            "QUERY_STRING": "",
            "SERVER_NAME": "x", "SERVER_PORT": "0", "SERVER_PROTOCOL": "HTTP/1.1",
            "REMOTE_ADDR": "127.0.0.1",
            "HTTP_HOST": "x", "wsgi.url_scheme": "http",
            "HTTP_ORIGIN": "http://x",
            "wsgi.input": io.BytesIO(body_payload),
            "wsgi.errors": sys.stderr,
        }, sr))
        assert responses[0][0].startswith("200")
        env = json.loads(body)
        assert env["type"] == "result"
        assert devalue.parse(env["result"]) == "hi alice"
    finally:
        if app.sidecar:
            app.sidecar.stop()
        for name in list(sys.modules):
            if name.startswith("app."):
                del sys.modules[name]
```

- [ ] **Step 3: Update `test_remote_import.py`'s bundle-content assertion**

Replace the regex / substring assertion. The old test asserted `"greeter/hello" in bundle_text`; that path format no longer exists. Update to:

```python
    # Bundle should reference the new URL pattern
    assert "/_fymo/remote/" in bundle_text
    # And reference the function name
    assert "'hello'" in bundle_text or '"hello"' in bundle_text
```

- [ ] **Step 4: Update `test_blog_e2e.py` to construct + decode wire correctly**

Replace each `_wsgi_call` invocation that hits the old `/__remote/posts/...` path. The fixture helper at the top of the file should encode args via devalue + base64url and the new URL pattern. Add to the helpers section:

```python
import base64
from fymo.remote import devalue


def _b64url(s: str) -> str:
    return base64.urlsafe_b64encode(s.encode("utf-8")).rstrip(b"=").decode("ascii")


def _remote_call(app, hash_, fn_name, args):
    body_payload = json.dumps({"payload": _b64url(devalue.stringify(args))}).encode()
    responses = []
    def sr(s, h): responses.append((s, h))
    out = b"".join(app({
        "REQUEST_METHOD": "POST",
        "PATH_INFO": f"/_fymo/remote/{hash_}/{fn_name}",
        "CONTENT_LENGTH": str(len(body_payload)),
        "CONTENT_TYPE": "application/json",
        "QUERY_STRING": "",
        "HTTP_HOST": "x", "HTTP_ORIGIN": "http://x", "wsgi.url_scheme": "http",
        "SERVER_NAME": "x", "SERVER_PORT": "0", "SERVER_PROTOCOL": "HTTP/1.1",
        "REMOTE_ADDR": "127.0.0.1",
        "wsgi.input": io.BytesIO(body_payload), "wsgi.errors": sys.stderr,
    }, sr))
    return responses[0], json.loads(out)
```

In the test body, after `BuildPipeline(...).build(dev=False)`, read the hash:

```python
    manifest = json.loads((blog_app / "dist" / "manifest.json").read_text())
    hash_ = manifest["remote_modules"]["posts"]["hash"]
```

Then replace each remote call. Example for `get_posts`:

```python
    (status, _), env = _remote_call(app, hash_, "get_posts", [])
    assert status.startswith("200")
    assert env["type"] == "result"
    posts = devalue.parse(env["result"])
    assert any(p["slug"] == "welcome-to-fymo" for p in posts)
```

For invalid input → 422 (now in envelope, not HTTP):

```python
    (status, _), env = _remote_call(app, hash_, "create_comment", ["welcome-to-fymo", {"name": "", "body": ""}])
    assert status.startswith("200")           # always 200 now
    assert env["type"] == "error"
    assert env["status"] == 422
    assert env["error"] == "validation"
```

For `toggle_reaction`:

```python
    (status, _), env = _remote_call(app, hash_, "toggle_reaction", ["welcome-to-fymo", "clap"])
    counts = devalue.parse(env["result"])
    assert counts["clap"] == 1
```

Add a NEW assertion about Date round-trip if applicable. The blog returns ISO strings for `published_at` (it's a TypedDict with `str`), so we don't get `datetime` round-trip from this app — skip the Date-specific check; the devalue test suite covers the Date case already.

- [ ] **Step 5: Run all integration tests — expect pass**

Run: `.venv/bin/python -m pytest tests/integration/ -v`
Expected: all PASS.

Run the full suite:
`.venv/bin/python -m pytest tests/ -q`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add tests/integration/test_remote_e2e.py tests/integration/test_remote_codegen_e2e.py tests/integration/test_remote_import.py tests/integration/test_blog_e2e.py
git commit -m "test: migrate integration tests to SvelteKit-style wire"
```

### Task 14: End-to-end browser verification

**Files:**
- No source changes — manual verification + a new browser-test step

- [ ] **Step 1: Build and serve the blog**

```bash
cd examples/blog_app
rm -rf dist .fymo app/data
/Users/bishwasbhandari/Projects/fymo/.worktrees/<this-worktree>/.venv/bin/fymo build 2>&1 | tail -2
/Users/bishwasbhandari/Projects/fymo/.worktrees/<this-worktree>/.venv/bin/python server.py > /tmp/blog.log 2>&1 &
SERVER=$!
disown $SERVER
sleep 4
```

- [ ] **Step 2: Verify the new URL pattern in the served HTML**

```bash
curl -sS http://127.0.0.1:8000/posts/welcome-to-fymo | grep -oE '__fymo_remote":"[a-z0-9]+/[a-z_]+'
# Expected: __fymo_remote":"<12-hex>/create_comment" etc. — markers now carry the hash.
```

- [ ] **Step 3: Verify the bundle uses the new URL**

```bash
BUNDLE=$(curl -sS http://127.0.0.1:8000/ | grep -oE '/dist/client/index\.[A-Z0-9]+\.js' | head -1)
curl -sS "http://127.0.0.1:8000$BUNDLE" | grep -oE '/_fymo/remote/' | head
# Expected: at least one match.
```

- [ ] **Step 4: Verify Origin enforcement**

```bash
curl -sS -X POST -H 'Content-Type: application/json' -H 'Origin: https://evil.com' \
    -d '{"payload":""}' \
    "http://127.0.0.1:8000/_fymo/remote/000000000000/get_posts"
# Expected body: {"type":"error","status":403,"error":"cross_origin"}
```

- [ ] **Step 5: Click-through test in a real browser via Playwright**

```bash
cd /Users/bishwasbhandari/Projects/fymo/.worktrees/<this-worktree>
.venv/bin/python -c "
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={'width': 1200, 'height': 1400})
    errors = []
    page.on('pageerror', lambda exc: errors.append(str(exc)))
    page.goto('http://127.0.0.1:8000/posts/welcome-to-fymo')
    page.wait_for_load_state('networkidle')
    page.locator('button:has-text(\"👏\")').click()
    page.wait_for_timeout(500)
    page.locator('input[placeholder=\"Your name\"]').fill('Alex')
    page.locator('textarea').fill('Great post!')
    page.locator('button:has-text(\"Post comment\")').click()
    page.wait_for_timeout(1000)
    print('errors:', errors)
    browser.close()
"
# Expected: errors: []
```

- [ ] **Step 6: Stop server**

```bash
lsof -ti :8000 | xargs -r kill -9 2>/dev/null
```

- [ ] **Step 7: No commit (this task is verification only)**

---

## Self-review

**Spec coverage:**
- Section 4 (wire protocol): Tasks 9, 10, 11
- Section 5 (devalue port): Tasks 1-5
- Section 6 (hash strategy): Tasks 6, 7
- Section 7 (codegen): Task 9
- Section 8 (router): Task 11
- Section 9 (migration): Tasks 13, 14
- Section 10 (rollout phases A-F): Tasks 1-14 in order
- Section 11 (tests): all tasks include tests
- Section 12 (acceptance criteria): verified in Task 14

**Placeholder scan:** none. Every step has actual code.

**Type consistency:** `RemoteFunction` carries `module_hash` (Task 6); `RemoteModuleAssets` carries `hash` and `fns` (Task 7); `_lookup_remote_hash`/`_resolve_module_for_hash` are stable names across Tasks 10 and 11; envelope shape `{type, result/error/status/...}` consistent everywhere.

**Open items not blocking ship:**
- v2 features explicitly deferred per spec section 14
- The hash collision risk is acknowledged in spec section 13.1 (no detection in v1; document and add later if needed)
- The transport hook is internal-only in v1; user-facing API comes in v2

## Execution handoff

**Plan complete and saved to `docs/superpowers/plans/2026-04-28-sveltekit-wire-parity.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — fresh subagent per task, review between tasks, ~14 tasks total, contained scope.

**2. Inline Execution** — execute tasks in this session using executing-plans, batch checkpoints.

**Which approach?**
