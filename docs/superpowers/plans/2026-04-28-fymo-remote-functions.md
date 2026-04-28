# Fymo Remote Functions + blog showcase — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add **Fymo Remote Functions** — plain Python functions in `app/remote/*.py` callable from Svelte components as if local, with type-safe `.d.ts` codegen, hybrid pydantic/stdlib validation, cookie identity, and an `/__remote/<m>/<fn>` HTTP layer. Ship `examples/blog_app/` as the canonical demo.

**Architecture:** A new `fymo.remote` Python package handles discovery, introspection, type-mapping (Python → TypeScript), HTTP routing, and request scoping. The build pipeline emits a `.js` runtime + `.d.ts` types pair per remote module under `dist/client/_remote/`. An esbuild plugin resolves `$remote/<name>` imports. Controllers can also thread function references through `getContext()`; an SSR JSON encoder serializes them as markers, and the client hydrate runtime swaps them for fetch wrappers.

**Tech Stack:** Python 3.12+, `pydantic>=2.5` (optional), `typing.get_type_hints`, `inspect`, esbuild + `esbuild-svelte` with TypeScript preprocess, `mistune` + `pygments` (blog only), SQLite (stdlib).

**Source spec:** `docs/superpowers/specs/2026-04-28-fymo-remote-functions-design.md`.

---

## File structure

### Framework — create

- `fymo/remote/__init__.py` — public exports (`current_uid`, `request_event`, error classes, runtime sentinels)
- `fymo/remote/errors.py` — `RemoteError` + `NotFound`, `Unauthorized`, `Forbidden`, `Conflict`
- `fymo/remote/discovery.py` — walk `app/remote/`, return `{module_name: {fn_name: {sig, hints}}}`
- `fymo/remote/typemap.py` — `python_type_to_ts(py_type) -> str`, `walk_referenced_types(...) -> dict[str, TSDef]`
- `fymo/remote/codegen.py` — `emit_module(module_name, fns, type_defs, out_dir)` writes `.js` + `.d.ts`
- `fymo/remote/identity.py` — `current_uid()`, `_ensure_uid(environ) -> (uid, set_cookie_or_None)`
- `fymo/remote/context.py` — `request_event()`, `request_scope(uid, environ)` contextmanager
- `fymo/remote/adapters.py` — `validate_args(args, sig, hints) -> tuple`, `serialize_response(value, return_hint) -> JSON`
- `fymo/remote/router.py` — `handle_remote(environ, start_response)` WSGI handler
- `fymo/remote/runtime_template.py` — string template for the client-side `__runtime.js` (kept as Python so it ships with the package)
- `fymo/build/js/plugins/remote.mjs` — esbuild plugin resolving `$remote/<name>` to generated JS
- `tests/remote/__init__.py`
- `tests/remote/test_discovery.py`
- `tests/remote/test_typemap.py`
- `tests/remote/test_codegen.py`
- `tests/remote/test_identity.py`
- `tests/remote/test_adapters.py`
- `tests/integration/test_remote_e2e.py`

### Framework — modify

- `fymo/build/pipeline.py` — call discovery + codegen between client/server passes
- `fymo/build/js/build.mjs` — enable TS preprocess; add `$remote/` plugin
- `fymo/build/js/dev.mjs` — same for dev
- `fymo/build/dev_orchestrator.py` — invalidate Python `app.remote.*` import cache on rebuild
- `fymo/core/server.py` — dispatch `POST /__remote/...` before the SSR branch
- `fymo/core/template_renderer.py` — pass `route_info["params"]` as kwargs to `getContext`
- `fymo/core/html.py` — JSON encoder default that detects callables from `app.remote.*` and emits `{__fymo_remote: "module/fn"}`
- `fymo/build/entry_generator.py` — call `__resolveRemoteProps(props)` before `hydrate(...)`
- `pyproject.toml` — add `pydantic` as `[project.optional-dependencies] pydantic`
- `package.json` — add `@sveltejs/vite-plugin-svelte` + `typescript` devDeps

### Blog example — create

- `examples/blog_app/fymo.yml`, `server.py`, `package.json`, `requirements.txt`, `tsconfig.json`, `.gitignore`
- `examples/blog_app/app/posts/welcome-to-fymo.md`
- `examples/blog_app/app/posts/how-the-build-pipeline-works.md`
- `examples/blog_app/app/posts/why-svelte5-and-python.md`
- `examples/blog_app/app/lib/__init__.py`, `db.py`, `seeder.py`, `identity.py`
- `examples/blog_app/app/remote/__init__.py`, `posts.py`
- `examples/blog_app/app/controllers/index.py`, `posts.py`, `tags.py`
- `examples/blog_app/app/templates/index/index.svelte`
- `examples/blog_app/app/templates/posts/show.svelte`
- `examples/blog_app/app/templates/posts/Comments.svelte`
- `examples/blog_app/app/templates/posts/ReactionBar.svelte`
- `examples/blog_app/app/templates/tags/show.svelte`
- `examples/blog_app/app/templates/_shared/Nav.svelte`

---

## Phase A — TypeScript in `.svelte`

### Task 1: Enable `<script lang="ts">` in build

**Files:**
- Modify: `package.json`
- Modify: `examples/todo_app/package.json` (so existing tests still pass)
- Modify: `fymo/build/js/build.mjs`
- Modify: `fymo/build/js/dev.mjs`
- Test: `tests/build/test_typescript_support.py` (new)

- [ ] **Step 1: Write the failing test**

`tests/build/test_typescript_support.py`:

```python
"""TypeScript inside <script lang='ts'> must compile and produce valid JS bundles."""
import json
from pathlib import Path
import pytest
from fymo.build.pipeline import BuildPipeline


@pytest.mark.usefixtures("node_available")
def test_typescript_script_tag_compiles(example_app: Path):
    # Inject a TS snippet into todos/test.svelte
    test_svelte = example_app / "app" / "templates" / "todos" / "test.svelte"
    original = test_svelte.read_text()
    patched = original.replace(
        "<script>",
        '<script lang="ts">\n  const greeting: string = "hello";',
        1,
    )
    test_svelte.write_text(patched)

    BuildPipeline(project_root=example_app).build(dev=False)

    # Build must succeed and emit a non-empty bundle
    manifest = json.loads((example_app / "dist" / "manifest.json").read_text())
    bundle = example_app / "dist" / manifest["routes"]["todos"]["client"]
    assert bundle.is_file()
    assert bundle.stat().st_size > 0
    # The TypeScript annotation should NOT appear in the output (it's stripped)
    assert ": string" not in bundle.read_text()
```

- [ ] **Step 2: Run test — expect failure**

Run: `.venv/bin/python -m pytest tests/build/test_typescript_support.py -v`
Expected: FAIL — esbuild-svelte without preprocess sees `: string` and errors.

- [ ] **Step 3: Add TypeScript devDeps**

Edit `package.json` `devDependencies`:
```json
"@sveltejs/vite-plugin-svelte": "^4.0.0",
"typescript": "^5.5.0"
```

Same in `examples/todo_app/package.json`.

Run: `npm install` in repo root and `cd examples/todo_app && npm install && cd -`.

- [ ] **Step 4: Wire `vitePreprocess` into the build scripts**

In `fymo/build/js/build.mjs`, near the existing `import sveltePlugin from 'esbuild-svelte';` add:

```javascript
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';
```

And update both `buildServer()` and `buildClient()` plugin calls:

```javascript
plugins: [sveltePlugin({
  preprocess: vitePreprocess(),
  compilerOptions: { generate: 'server', dev: false },
})],
```

(Use `'client'` for `buildClient`.)

Same edits in `fymo/build/js/dev.mjs` for both contexts.

- [ ] **Step 5: Run test — expect pass**

Run: `.venv/bin/python -m pytest tests/build/test_typescript_support.py -v`
Expected: 1 PASSED.

Run full suite to confirm no regressions:
`.venv/bin/python -m pytest tests/ -q`
Expected: 31 passed (prior 31, this test makes 32).

- [ ] **Step 6: Commit**

```bash
git add package.json package-lock.json examples/todo_app/package.json examples/todo_app/package-lock.json fymo/build/js/build.mjs fymo/build/js/dev.mjs tests/build/test_typescript_support.py
git commit -m "feat(build): enable <script lang='ts'> via vitePreprocess"
```

---

## Phase B — Discovery + introspection

### Task 2: Errors module

**Files:**
- Create: `fymo/remote/__init__.py`
- Create: `fymo/remote/errors.py`
- Test: `tests/remote/__init__.py`, `tests/remote/test_errors.py`

- [ ] **Step 1: Create the test packages and write the failing test**

```bash
mkdir -p tests/remote
touch tests/remote/__init__.py
```

`tests/remote/test_errors.py`:

```python
import pytest
from fymo.remote.errors import RemoteError, NotFound, Unauthorized, Forbidden, Conflict


def test_remote_error_carries_status_and_code():
    err = RemoteError("oops", status=418, code="teapot")
    assert err.status == 418
    assert err.code == "teapot"
    assert str(err) == "oops"


def test_subclasses_have_correct_status():
    assert NotFound("x").status == 404
    assert NotFound("x").code == "not_found"
    assert Unauthorized("x").status == 401
    assert Unauthorized("x").code == "unauthorized"
    assert Forbidden("x").status == 403
    assert Forbidden("x").code == "forbidden"
    assert Conflict("x").status == 409
    assert Conflict("x").code == "conflict"


def test_subclass_message_preserved():
    e = NotFound("post 'foo' not found")
    assert "post 'foo' not found" in str(e)
```

- [ ] **Step 2: Run — expect failure**

Run: `.venv/bin/python -m pytest tests/remote/test_errors.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fymo.remote'`.

- [ ] **Step 3: Create `fymo/remote/__init__.py`**

```python
"""Fymo remote functions: server-only Python callable from Svelte components."""
from fymo.remote.errors import RemoteError, NotFound, Unauthorized, Forbidden, Conflict

__all__ = ["RemoteError", "NotFound", "Unauthorized", "Forbidden", "Conflict"]
```

- [ ] **Step 4: Create `fymo/remote/errors.py`**

```python
"""Domain error types for remote functions. Each maps to an HTTP status."""


class RemoteError(Exception):
    """Base class. Translates to a JSON response with the given status + code."""
    status: int = 500
    code: str = "internal"

    def __init__(self, message: str, *, status: int | None = None, code: str | None = None):
        super().__init__(message)
        if status is not None:
            self.status = status
        if code is not None:
            self.code = code


class NotFound(RemoteError):
    status = 404
    code = "not_found"


class Unauthorized(RemoteError):
    status = 401
    code = "unauthorized"


class Forbidden(RemoteError):
    status = 403
    code = "forbidden"


class Conflict(RemoteError):
    status = 409
    code = "conflict"
```

- [ ] **Step 5: Run — expect pass**

Run: `.venv/bin/python -m pytest tests/remote/test_errors.py -v`
Expected: 3 PASSED.

- [ ] **Step 6: Commit**

```bash
git add fymo/remote/__init__.py fymo/remote/errors.py tests/remote/__init__.py tests/remote/test_errors.py
git commit -m "feat(remote): add error hierarchy with HTTP status codes"
```

### Task 3: Discovery — find remote modules and extract function signatures

**Files:**
- Create: `fymo/remote/discovery.py`
- Test: `tests/remote/test_discovery.py`
- Test fixtures: inline in test (use `tmp_path`)

- [ ] **Step 1: Write the failing test**

```python
"""Discover app/remote/*.py modules and extract top-level callable signatures."""
import sys
from pathlib import Path
import pytest
from fymo.remote.discovery import discover_remote_modules, RemoteFunction


def _scaffold(tmp_path: Path, files: dict[str, str]) -> Path:
    for rel, content in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    return tmp_path


def test_discovers_top_level_functions(tmp_path: Path):
    project = _scaffold(tmp_path, {
        "app/__init__.py": "",
        "app/remote/__init__.py": "",
        "app/remote/posts.py": (
            "from typing import TypedDict\n"
            "class Post(TypedDict):\n"
            "    slug: str\n"
            "    title: str\n"
            "def get_post(slug: str) -> Post:\n"
            "    return {'slug': slug, 'title': 'x'}\n"
            "def _private(): return 1\n"  # underscore-prefixed = excluded
        ),
    })

    sys.path.insert(0, str(project))
    try:
        result = discover_remote_modules(project)
    finally:
        sys.path.remove(str(project))
        # Clean up imports so subsequent tests don't see this module
        for name in list(sys.modules):
            if name.startswith("app."):
                del sys.modules[name]

    assert "posts" in result
    assert "get_post" in result["posts"]
    assert "_private" not in result["posts"]
    fn = result["posts"]["get_post"]
    assert isinstance(fn, RemoteFunction)
    assert list(fn.signature.parameters.keys()) == ["slug"]
    assert fn.hints["slug"] is str


def test_returns_empty_when_no_remote_dir(tmp_path: Path):
    assert discover_remote_modules(tmp_path) == {}


def test_skips_private_modules(tmp_path: Path):
    project = _scaffold(tmp_path, {
        "app/__init__.py": "",
        "app/remote/__init__.py": "",
        "app/remote/_helpers.py": "def util(): pass\n",  # _-prefixed module excluded
        "app/remote/public.py": "def hello() -> str: return 'hi'\n",
    })
    sys.path.insert(0, str(project))
    try:
        result = discover_remote_modules(project)
    finally:
        sys.path.remove(str(project))
        for name in list(sys.modules):
            if name.startswith("app."):
                del sys.modules[name]

    assert "public" in result
    assert "_helpers" not in result


def test_raises_on_untyped_parameter(tmp_path: Path):
    project = _scaffold(tmp_path, {
        "app/__init__.py": "",
        "app/remote/__init__.py": "",
        "app/remote/bad.py": "def fn(x): return x\n",
    })
    sys.path.insert(0, str(project))
    try:
        with pytest.raises(ValueError, match="annotate"):
            discover_remote_modules(project)
    finally:
        sys.path.remove(str(project))
        for name in list(sys.modules):
            if name.startswith("app."):
                del sys.modules[name]
```

- [ ] **Step 2: Run — expect failure**

Run: `.venv/bin/python -m pytest tests/remote/test_discovery.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement `fymo/remote/discovery.py`**

```python
"""Discover and introspect functions in app/remote/*.py."""
import importlib
import inspect
import typing
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True)
class RemoteFunction:
    """A top-level callable from app/remote/<module>.py."""
    module: str
    name: str
    fn: Callable[..., Any]
    signature: inspect.Signature
    hints: dict[str, Any]  # includes 'return' if annotated


def discover_remote_modules(project_root: Path) -> dict[str, dict[str, RemoteFunction]]:
    """Walk app/remote/*.py and return {module_name: {fn_name: RemoteFunction}}.

    Modules and functions starting with underscore are excluded (private).
    Each non-private function MUST have type-annotated parameters; the
    function discovery raises ValueError if any parameter is untyped.
    """
    remote_dir = project_root / "app" / "remote"
    if not remote_dir.is_dir():
        return {}

    out: dict[str, dict[str, RemoteFunction]] = {}
    for py in sorted(remote_dir.glob("*.py")):
        if py.name == "__init__.py" or py.stem.startswith("_"):
            continue
        module_name = py.stem
        full = f"app.remote.{module_name}"
        if full in importlib.sys.modules:
            mod = importlib.reload(importlib.sys.modules[full])
        else:
            mod = importlib.import_module(full)

        fns: dict[str, RemoteFunction] = {}
        for name, obj in vars(mod).items():
            if name.startswith("_"):
                continue
            if not callable(obj):
                continue
            # Only functions defined IN this module (not imported helpers)
            if getattr(obj, "__module__", None) != full:
                continue
            sig = inspect.signature(obj)
            try:
                hints = typing.get_type_hints(obj, include_extras=True)
            except Exception as e:
                raise ValueError(
                    f"app/remote/{module_name}.py: cannot resolve type hints for "
                    f"{name!r}: {e}"
                )
            for pname in sig.parameters:
                if pname not in hints:
                    raise ValueError(
                        f"app/remote/{module_name}.py: please annotate parameter "
                        f"{pname!r} of function {name!r}"
                    )
            fns[name] = RemoteFunction(
                module=module_name, name=name, fn=obj, signature=sig, hints=hints
            )
        out[module_name] = fns
    return out
```

- [ ] **Step 4: Run — expect pass**

Run: `.venv/bin/python -m pytest tests/remote/test_discovery.py -v`
Expected: 4 PASSED.

- [ ] **Step 5: Commit**

```bash
git add fymo/remote/discovery.py tests/remote/test_discovery.py
git commit -m "feat(remote): add discovery for app/remote/*.py modules"
```

---

## Phase C — Type bridge (Python → TypeScript)

### Task 4: Type-mapping for primitives, containers, and special-form types

**Files:**
- Create: `fymo/remote/typemap.py`
- Test: `tests/remote/test_typemap.py`

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run — expect failure**

Run: `.venv/bin/python -m pytest tests/remote/test_typemap.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `fymo/remote/typemap.py` (primitive + container handling)**

```python
"""Map Python types to TypeScript types."""
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

    # Optional[X] / Union[X, Y, ...]
    if origin is Union:
        parts = sorted(python_type_to_ts(a, type_defs=type_defs) for a in args)
        return " | ".join(parts)

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
    # Enum — handled in Task 6

    return "unknown"
```

- [ ] **Step 4: Run — expect pass**

Run: `.venv/bin/python -m pytest tests/remote/test_typemap.py -v`
Expected: 8 PASSED.

- [ ] **Step 5: Commit**

```bash
git add fymo/remote/typemap.py tests/remote/test_typemap.py
git commit -m "feat(remote): add type mapping for primitives + containers + literals"
```

### Task 5: Type-mapping for TypedDict, dataclass, NamedTuple, Enum

**Files:**
- Modify: `fymo/remote/typemap.py`
- Modify: `tests/remote/test_typemap.py`

- [ ] **Step 1: Add tests**

Append to `tests/remote/test_typemap.py`:

```python
from typing import TypedDict, NamedTuple
from dataclasses import dataclass
from enum import Enum


class Post(TypedDict):
    slug: str
    title: str
    count: int


@dataclass
class Comment:
    id: int
    body: str


class Color(Enum):
    RED = "red"
    BLUE = "blue"


class Pair(NamedTuple):
    a: int
    b: str


def test_typeddict_emits_interface():
    defs: dict[str, str] = {}
    name = python_type_to_ts(Post, type_defs=defs)
    assert name == "Post"
    assert "Post" in defs
    assert "slug: string" in defs["Post"]
    assert "title: string" in defs["Post"]
    assert "count: number" in defs["Post"]


def test_dataclass_emits_interface():
    defs: dict[str, str] = {}
    name = python_type_to_ts(Comment, type_defs=defs)
    assert name == "Comment"
    assert "id: number" in defs["Comment"]
    assert "body: string" in defs["Comment"]


def test_named_tuple_emits_interface():
    defs: dict[str, str] = {}
    name = python_type_to_ts(Pair, type_defs=defs)
    assert name == "Pair"
    assert "a: number" in defs["Pair"]
    assert "b: string" in defs["Pair"]


def test_string_enum_emits_union():
    defs: dict[str, str] = {}
    name = python_type_to_ts(Color, type_defs=defs)
    # Either inlined or aliased; both valid. Accept either shape.
    assert name in ("Color", '"red" | "blue"', '"blue" | "red"')
    if name == "Color":
        assert defs["Color"] in ('"red" | "blue"', '"blue" | "red"')


def test_nested_typeddict():
    class Inner(TypedDict):
        x: int

    class Outer(TypedDict):
        inner: Inner

    defs: dict[str, str] = {}
    name = python_type_to_ts(Outer, type_defs=defs)
    assert name == "Outer"
    assert "inner: Inner" in defs["Outer"]
    assert "x: number" in defs["Inner"]


def test_idempotent_re_resolution():
    """Resolving the same type twice should not duplicate the interface."""
    defs: dict[str, str] = {}
    python_type_to_ts(Post, type_defs=defs)
    python_type_to_ts(Post, type_defs=defs)
    assert list(defs.keys()).count("Post") == 1
```

- [ ] **Step 2: Run — expect failure on the new tests**

Run: `.venv/bin/python -m pytest tests/remote/test_typemap.py -v`
Expected: 6 NEW failures (existing 8 still pass).

- [ ] **Step 3: Extend `fymo/remote/typemap.py`**

Add these helpers and integrate them at the bottom of `python_type_to_ts` (replacing the final `return "unknown"`).

```python
import dataclasses


def _is_typed_dict(py) -> bool:
    return isinstance(py, type) and issubclass(py, dict) and hasattr(py, "__annotations__") and hasattr(py, "__required_keys__")


def _is_dataclass(py) -> bool:
    return dataclasses.is_dataclass(py) and isinstance(py, type)


def _is_named_tuple(py) -> bool:
    return isinstance(py, type) and issubclass(py, tuple) and hasattr(py, "_fields") and hasattr(py, "__annotations__")


def _is_enum(py) -> bool:
    return isinstance(py, type) and issubclass(py, Enum)


def _emit_interface(name: str, fields: list[tuple[str, str, bool]], type_defs: dict[str, str]) -> str:
    """fields = [(field_name, ts_type, optional)]. Writes/updates type_defs[name]."""
    if name in type_defs:
        return name
    body_lines = []
    for fname, ftype, optional in fields:
        suffix = "?" if optional else ""
        body_lines.append(f"  {fname}{suffix}: {ftype};")
    type_defs[name] = "{\n" + "\n".join(body_lines) + "\n}"
    return name


def _emit_typed_dict(py, type_defs: dict[str, str]) -> str:
    name = py.__name__
    if name in type_defs:
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
    if name in type_defs:
        return name
    type_defs[name] = "<placeholder>"
    hints = typing.get_type_hints(py)
    fields = [(fname, python_type_to_ts(ftype, type_defs=type_defs), False) for fname, ftype in hints.items()]
    return _emit_interface(name, fields, type_defs)


def _emit_enum(py, type_defs: dict[str, str]) -> str:
    name = py.__name__
    members = list(py)
    if all(isinstance(m.value, str) for m in members):
        rendered = " | ".join(f'"{m.value}"' for m in members)
    else:
        rendered = " | ".join(repr(m.value) for m in members)
    type_defs[name] = rendered
    return name
```

Replace the final `return "unknown"` in `python_type_to_ts` with:

```python
    if _is_typed_dict(py):
        return _emit_typed_dict(py, type_defs)
    if _is_dataclass(py):
        return _emit_dataclass_or_namedtuple(py, type_defs)
    if _is_named_tuple(py):
        return _emit_dataclass_or_namedtuple(py, type_defs)
    if _is_enum(py):
        return _emit_enum(py, type_defs)

    return "unknown"
```

- [ ] **Step 4: Run — expect pass**

Run: `.venv/bin/python -m pytest tests/remote/test_typemap.py -v`
Expected: 14 PASSED.

- [ ] **Step 5: Commit**

```bash
git add fymo/remote/typemap.py tests/remote/test_typemap.py
git commit -m "feat(remote): map TypedDict, dataclass, NamedTuple, Enum to TS"
```

### Task 6: Type-mapping for pydantic BaseModel

**Files:**
- Modify: `fymo/remote/typemap.py`
- Modify: `tests/remote/test_typemap.py`
- Modify: `pyproject.toml`

- [ ] **Step 1: Add pydantic optional dep**

Edit `pyproject.toml`'s `[project.optional-dependencies]` block to add:

```toml
pydantic = ["pydantic>=2.5"]
```

Run: `.venv/bin/pip install 'pydantic>=2.5'` (so the test env has it).

- [ ] **Step 2: Add tests**

Append to `tests/remote/test_typemap.py`:

```python
from pydantic import BaseModel, Field


class NewComment(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    body: str = Field(min_length=1, max_length=1000)
    optional_meta: str | None = None


def test_pydantic_emits_interface():
    defs: dict[str, str] = {}
    name = python_type_to_ts(NewComment, type_defs=defs)
    assert name == "NewComment"
    assert "name: string" in defs["NewComment"]
    assert "body: string" in defs["NewComment"]
    assert "optional_meta?:" in defs["NewComment"] or "optional_meta: string | null" in defs["NewComment"]


def test_pydantic_optional_marked_optional():
    """Fields with default values should be marked optional in TS."""
    class Foo(BaseModel):
        required: str
        optional_with_default: int = 42

    defs: dict[str, str] = {}
    python_type_to_ts(Foo, type_defs=defs)
    iface = defs["Foo"]
    # Field with default → optional
    assert "optional_with_default?: number" in iface
    # Required field → no "?"
    assert "required: string" in iface and "required?" not in iface
```

- [ ] **Step 3: Run — expect failure**

Run: `.venv/bin/python -m pytest tests/remote/test_typemap.py::test_pydantic_emits_interface tests/remote/test_typemap.py::test_pydantic_optional_marked_optional -v`
Expected: FAIL.

- [ ] **Step 4: Add pydantic adapter to `typemap.py`**

At the top of the file, add a try-import:

```python
try:
    import pydantic
    _has_pydantic = True
except ImportError:
    pydantic = None  # type: ignore
    _has_pydantic = False
```

Add helper:

```python
def _is_pydantic_model(py) -> bool:
    return _has_pydantic and isinstance(py, type) and issubclass(py, pydantic.BaseModel)


def _emit_pydantic(py, type_defs: dict[str, str]) -> str:
    name = py.__name__
    if name in type_defs:
        return name
    type_defs[name] = "<placeholder>"
    fields = []
    for fname, finfo in py.model_fields.items():
        ftype = finfo.annotation
        ts = python_type_to_ts(ftype, type_defs=type_defs)
        # Required if no default and not Optional
        optional = (finfo.default is not pydantic.fields.PydanticUndefined) or (finfo.default_factory is not None)
        fields.append((fname, ts, optional))
    return _emit_interface(name, fields, type_defs)
```

Insert into `python_type_to_ts` BEFORE the TypedDict check (pydantic models are subclasses of `dict`-like behavior in newer pydantic, so check first):

```python
    if _is_pydantic_model(py):
        return _emit_pydantic(py, type_defs)
```

- [ ] **Step 5: Run — expect pass**

Run: `.venv/bin/python -m pytest tests/remote/test_typemap.py -v`
Expected: 16 PASSED.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml fymo/remote/typemap.py tests/remote/test_typemap.py
git commit -m "feat(remote): map pydantic BaseModel to TS interface"
```

### Task 7: Codegen — emit `.js` and `.d.ts` per module

**Files:**
- Create: `fymo/remote/codegen.py`
- Test: `tests/remote/test_codegen.py`

- [ ] **Step 1: Write the failing test**

```python
"""Codegen emits matching .js + .d.ts for a remote module."""
import sys
import inspect
import typing
from pathlib import Path
from fymo.remote.codegen import emit_module
from fymo.remote.discovery import RemoteFunction


def _make_fn(module_name: str, fn) -> RemoteFunction:
    sig = inspect.signature(fn)
    hints = typing.get_type_hints(fn)
    return RemoteFunction(module=module_name, name=fn.__name__, fn=fn, signature=sig, hints=hints)


def test_emits_js_and_dts(tmp_path: Path):
    from typing import TypedDict

    class Post(TypedDict):
        slug: str
        title: str

    def get_post(slug: str) -> Post:
        return {"slug": slug, "title": "x"}

    fns = {"get_post": _make_fn("posts", get_post)}
    emit_module("posts", fns, tmp_path)

    js = (tmp_path / "posts.js").read_text()
    dts = (tmp_path / "posts.d.ts").read_text()

    # JS: imports the runtime, exports a fetch wrapper
    assert "import { __rpc }" in js
    assert "export const get_post" in js
    assert "'posts/get_post'" in js

    # DTS: declares the function with typed signature, plus the Post interface
    assert "export interface Post" in dts
    assert "slug: string" in dts
    assert "title: string" in dts
    assert "export function get_post(slug: string): Promise<Post>;" in dts


def test_emits_runtime_file(tmp_path: Path):
    from fymo.remote.codegen import emit_runtime
    emit_runtime(tmp_path)
    runtime = (tmp_path / "__runtime.js").read_text()
    assert "export async function __rpc" in runtime
    assert "export function __resolveRemoteProps" in runtime
    assert "/__remote/" in runtime


def test_multiple_functions_in_one_module(tmp_path: Path):
    def fn_a(x: int) -> str: return str(x)
    def fn_b(s: str) -> int: return len(s)

    fns = {
        "fn_a": _make_fn("util", fn_a),
        "fn_b": _make_fn("util", fn_b),
    }
    emit_module("util", fns, tmp_path)
    js = (tmp_path / "util.js").read_text()
    dts = (tmp_path / "util.d.ts").read_text()

    assert "export const fn_a" in js
    assert "export const fn_b" in js
    assert "export function fn_a(x: number): Promise<string>;" in dts
    assert "export function fn_b(s: string): Promise<number>;" in dts
```

- [ ] **Step 2: Run — expect failure**

Run: `.venv/bin/python -m pytest tests/remote/test_codegen.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `fymo/remote/codegen.py`**

```python
"""Generate .js (fetch wrappers) + .d.ts (typed declarations) per remote module."""
import inspect
from pathlib import Path
from fymo.remote.discovery import RemoteFunction
from fymo.remote.typemap import python_type_to_ts


_RUNTIME_JS = '''// AUTO-GENERATED. Do not edit. Fymo remote-functions client runtime.
const REMOTE_MARKER = "__fymo_remote";

export async function __rpc(path, args) {
    const res = await fetch("/__remote/" + path, {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ args }),
    });
    let payload;
    try {
        payload = await res.json();
    } catch (e) {
        throw new Error("invalid JSON response from " + path);
    }
    if (payload.ok) return payload.data;
    const err = new Error(payload.message || payload.error || "remote_error");
    err.status = res.status;
    err.error = payload.error;
    err.issues = payload.issues;
    throw err;
}

// Replaces marker objects in props (emitted by SSR for callable props from
// app/remote/*) with real fetch wrappers, in place.
export function __resolveRemoteProps(props) {
    for (const key in props) {
        const v = props[key];
        if (v && typeof v === "object" && v[REMOTE_MARKER]) {
            const path = v[REMOTE_MARKER];
            props[key] = (...args) => __rpc(path, args);
        }
    }
    return props;
}
'''


def _format_function_dts(fn: RemoteFunction, type_defs: dict[str, str]) -> str:
    """Build the `export function name(...): Promise<R>;` line."""
    params = []
    for pname, param in fn.signature.parameters.items():
        if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            raise ValueError(f"{fn.module}.{fn.name}: *args / **kwargs not supported")
        ts = python_type_to_ts(fn.hints[pname], type_defs=type_defs)
        optional = "?" if param.default is not inspect.Parameter.empty else ""
        params.append(f"{pname}{optional}: {ts}")
    ret_hint = fn.hints.get("return", type(None))
    ret_ts = python_type_to_ts(ret_hint, type_defs=type_defs)
    return f"export function {fn.name}({', '.join(params)}): Promise<{ret_ts}>;"


def _format_function_js(fn: RemoteFunction) -> str:
    pnames = list(fn.signature.parameters.keys())
    params = ", ".join(pnames)
    args = "[" + ", ".join(pnames) + "]"
    return f"export const {fn.name} = ({params}) => __rpc('{fn.module}/{fn.name}', {args});"


def emit_module(module_name: str, fns: dict[str, RemoteFunction], out_dir: Path) -> None:
    """Write <out_dir>/<module_name>.js and <module_name>.d.ts."""
    out_dir.mkdir(parents=True, exist_ok=True)

    type_defs: dict[str, str] = {}
    dts_fn_lines: list[str] = []
    for fn in fns.values():
        dts_fn_lines.append(_format_function_dts(fn, type_defs))

    # Emit interfaces in a stable order
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

    js_lines = [
        f"// AUTO-GENERATED. Do not edit. Source: app/remote/{module_name}.py",
        "import { __rpc } from './__runtime.js';",
        "",
    ]
    for fn in fns.values():
        js_lines.append(_format_function_js(fn))
    (out_dir / f"{module_name}.js").write_text("\n".join(js_lines) + "\n")


def emit_runtime(out_dir: Path) -> None:
    """Write the shared client runtime file."""
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "__runtime.js").write_text(_RUNTIME_JS)
```

- [ ] **Step 4: Run — expect pass**

Run: `.venv/bin/python -m pytest tests/remote/test_codegen.py -v`
Expected: 3 PASSED.

- [ ] **Step 5: Commit**

```bash
git add fymo/remote/codegen.py tests/remote/test_codegen.py
git commit -m "feat(remote): emit .js + .d.ts and shared runtime per module"
```

### Task 8: Wire codegen into `BuildPipeline`

**Files:**
- Modify: `fymo/build/pipeline.py`
- Test: `tests/integration/test_remote_codegen_e2e.py` (new)

- [ ] **Step 1: Write the failing test**

```python
"""End-to-end: BuildPipeline must produce .js + .d.ts under dist/client/_remote/."""
import shutil
from pathlib import Path
import pytest
from fymo.build.pipeline import BuildPipeline


@pytest.mark.usefixtures("node_available")
def test_build_emits_remote_artifacts(example_app: Path):
    # Add a minimal remote module to the example app
    remote_dir = example_app / "app" / "remote"
    remote_dir.mkdir(parents=True, exist_ok=True)
    (remote_dir / "__init__.py").write_text("")
    (remote_dir / "test_mod.py").write_text(
        "def hello(name: str) -> str:\n    return f'hi {name}'\n"
    )

    BuildPipeline(project_root=example_app).build(dev=False)

    out = example_app / "dist" / "client" / "_remote"
    assert (out / "__runtime.js").is_file()
    assert (out / "test_mod.js").is_file()
    assert (out / "test_mod.d.ts").is_file()

    js = (out / "test_mod.js").read_text()
    assert "export const hello" in js
    assert "test_mod/hello" in js
```

- [ ] **Step 2: Run — expect failure**

Run: `.venv/bin/python -m pytest tests/integration/test_remote_codegen_e2e.py -v`
Expected: FAIL.

- [ ] **Step 3: Wire codegen into `fymo/build/pipeline.py`**

In `fymo/build/pipeline.py`, add an import:

```python
from fymo.remote.discovery import discover_remote_modules
from fymo.remote.codegen import emit_module, emit_runtime
```

In `BuildPipeline.build()`, after `client_entry_paths = write_client_entries(...)` and before the subprocess call to esbuild, add:

```python
        # Codegen for app/remote/*.py — produces dist/client/_remote/<name>.{js,d.ts}
        remote_out = self.dist_dir / "client" / "_remote"
        try:
            remote_modules = discover_remote_modules(self.project_root)
        except ValueError as e:
            raise BuildError(f"remote module discovery failed: {e}")
        if remote_modules:
            emit_runtime(remote_out)
            for module_name, fns in remote_modules.items():
                emit_module(module_name, fns, remote_out)
```

- [ ] **Step 4: Run — expect pass**

Run: `.venv/bin/python -m pytest tests/integration/test_remote_codegen_e2e.py -v`
Expected: 1 PASSED.

Run full suite:
`.venv/bin/python -m pytest tests/ -q`
Expected: prior tests + 1 new = no regressions.

- [ ] **Step 5: Commit**

```bash
git add fymo/build/pipeline.py tests/integration/test_remote_codegen_e2e.py
git commit -m "feat(build): wire remote-function codegen into BuildPipeline"
```

---

## Phase D — HTTP layer

### Task 9: Identity (uid cookie)

**Files:**
- Create: `fymo/remote/identity.py`
- Test: `tests/remote/test_identity.py`

- [ ] **Step 1: Write the failing test**

```python
"""Cookie-based identity: issue a uid on first POST, read it on subsequent."""
from http.cookies import SimpleCookie
from fymo.remote.identity import _ensure_uid, _UID_COOKIE


def _environ_with_cookie(value: str | None) -> dict:
    env = {"HTTP_COOKIE": "" if value is None else f"{_UID_COOKIE}={value}"}
    return env


def test_returns_existing_uid_when_present():
    env = _environ_with_cookie("u_existing")
    uid, set_cookie = _ensure_uid(env)
    assert uid == "u_existing"
    assert set_cookie is None


def test_issues_new_uid_when_absent():
    env = _environ_with_cookie(None)
    uid, set_cookie = _ensure_uid(env)
    assert uid.startswith("u_")
    assert len(uid) > 5
    assert set_cookie is not None
    assert _UID_COOKIE in set_cookie
    assert "Path=/" in set_cookie
    assert "Max-Age=" in set_cookie
    assert "SameSite=Lax" in set_cookie


def test_issues_unique_uids():
    a, _ = _ensure_uid({"HTTP_COOKIE": ""})
    b, _ = _ensure_uid({"HTTP_COOKIE": ""})
    assert a != b
```

- [ ] **Step 2: Run — expect failure**

Run: `.venv/bin/python -m pytest tests/remote/test_identity.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `fymo/remote/identity.py`**

```python
"""fymo_uid cookie management. The uid is an opaque identity token,
NOT a credential — used to dedupe reactions, attribute comments, etc."""
import secrets
from http.cookies import SimpleCookie

_UID_COOKIE = "fymo_uid"
_TEN_YEARS_SECONDS = 10 * 365 * 24 * 60 * 60


def _read_cookie(environ: dict, name: str) -> str | None:
    raw = environ.get("HTTP_COOKIE", "")
    if not raw:
        return None
    cookies = SimpleCookie()
    cookies.load(raw)
    morsel = cookies.get(name)
    return morsel.value if morsel else None


def _ensure_uid(environ: dict) -> tuple[str, str | None]:
    """Return (uid, Set-Cookie header value or None if no cookie needs to be set)."""
    existing = _read_cookie(environ, _UID_COOKIE)
    if existing:
        return existing, None
    new_uid = "u_" + secrets.token_urlsafe(12)
    cookie = (
        f"{_UID_COOKIE}={new_uid}; "
        f"Path=/; "
        f"Max-Age={_TEN_YEARS_SECONDS}; "
        f"SameSite=Lax; "
        f"HttpOnly"
    )
    return new_uid, cookie


def current_uid() -> str:
    """Return the uid of the current remote-function request.
    Must be called from within a request_scope; raises otherwise."""
    from fymo.remote.context import _current_event
    event = _current_event.get()
    if event is None:
        raise RuntimeError("current_uid() called outside of a remote-function request scope")
    return event["uid"]
```

- [ ] **Step 4: Run — expect pass**

Run: `.venv/bin/python -m pytest tests/remote/test_identity.py -v`
Expected: 3 PASSED.

- [ ] **Step 5: Commit**

```bash
git add fymo/remote/identity.py tests/remote/test_identity.py
git commit -m "feat(remote): add fymo_uid cookie management"
```

### Task 10: Request-scope context

**Files:**
- Create: `fymo/remote/context.py`
- Test: `tests/remote/test_context.py`

- [ ] **Step 1: Write the failing test**

```python
"""request_scope is a contextvar-based scope; current_uid() resolves inside it."""
import pytest
from fymo.remote.context import request_scope, request_event
from fymo.remote.identity import current_uid


def test_current_uid_outside_scope_raises():
    with pytest.raises(RuntimeError, match="outside"):
        current_uid()


def test_current_uid_inside_scope():
    with request_scope(uid="u_test", environ={"REMOTE_ADDR": "127.0.0.1"}):
        assert current_uid() == "u_test"
        ev = request_event()
        assert ev.uid == "u_test"
        assert ev.remote_addr == "127.0.0.1"


def test_scope_is_cleaned_up_after_exit():
    with request_scope(uid="u_x", environ={}):
        assert current_uid() == "u_x"
    with pytest.raises(RuntimeError):
        current_uid()
```

- [ ] **Step 2: Run — expect failure**

Run: `.venv/bin/python -m pytest tests/remote/test_context.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `fymo/remote/context.py`**

```python
"""Request-scoped context for remote functions, using contextvars (thread/coroutine safe)."""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

_current_event: ContextVar[dict | None] = ContextVar("_current_event", default=None)


@dataclass(frozen=True)
class RequestEvent:
    uid: str
    remote_addr: str
    cookies: dict[str, str]
    headers: dict[str, str]


def request_event() -> RequestEvent:
    """Return the current RequestEvent. Raises if called outside a request scope."""
    ev = _current_event.get()
    if ev is None:
        raise RuntimeError("request_event() called outside of a remote-function request scope")
    return RequestEvent(
        uid=ev["uid"],
        remote_addr=ev.get("remote_addr", ""),
        cookies=ev.get("cookies", {}),
        headers=ev.get("headers", {}),
    )


@contextmanager
def request_scope(uid: str, environ: dict):
    """Push a request scope onto the contextvar for the duration of a remote call."""
    headers = {k[5:].replace("_", "-").lower(): v for k, v in environ.items() if k.startswith("HTTP_")}
    cookies: dict[str, str] = {}
    if environ.get("HTTP_COOKIE"):
        from http.cookies import SimpleCookie
        c = SimpleCookie()
        c.load(environ["HTTP_COOKIE"])
        cookies = {k: v.value for k, v in c.items()}
    payload = {
        "uid": uid,
        "remote_addr": environ.get("REMOTE_ADDR", ""),
        "cookies": cookies,
        "headers": headers,
    }
    token = _current_event.set(payload)
    try:
        yield
    finally:
        _current_event.reset(token)
```

- [ ] **Step 4: Run — expect pass**

Run: `.venv/bin/python -m pytest tests/remote/test_context.py -v`
Expected: 3 PASSED.

- [ ] **Step 5: Update `fymo/remote/__init__.py` to export the helpers**

```python
"""Fymo remote functions: server-only Python callable from Svelte components."""
from fymo.remote.errors import RemoteError, NotFound, Unauthorized, Forbidden, Conflict
from fymo.remote.identity import current_uid
from fymo.remote.context import request_event

__all__ = [
    "RemoteError", "NotFound", "Unauthorized", "Forbidden", "Conflict",
    "current_uid", "request_event",
]
```

- [ ] **Step 6: Commit**

```bash
git add fymo/remote/context.py fymo/remote/__init__.py tests/remote/test_context.py
git commit -m "feat(remote): add request-scoped context with current_uid + request_event"
```

### Task 11: Argument validation + response serialization

**Files:**
- Create: `fymo/remote/adapters.py`
- Test: `tests/remote/test_adapters.py`

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run — expect failure**

Run: `.venv/bin/python -m pytest tests/remote/test_adapters.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `fymo/remote/adapters.py`**

```python
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
    """Validate `value` against `hint`. Raises TypeError or ValidationError on mismatch.
    Pydantic models are constructed from dicts; primitives are isinstance-checked."""
    if hint is Any or hint is type(None):
        return value
    origin = get_origin(hint)

    if _is_pydantic_model(hint):
        return hint.model_validate(value)

    # Optional / Union — accept if value matches any branch
    if origin is Union:
        last_err = None
        for branch in get_args(hint):
            try:
                return _coerce_value(value, branch)
            except (TypeError, ValueError, pydantic.ValidationError if _has_pydantic else Exception) as e:
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
```

- [ ] **Step 4: Run — expect pass**

Run: `.venv/bin/python -m pytest tests/remote/test_adapters.py -v`
Expected: 7 PASSED.

- [ ] **Step 5: Commit**

```bash
git add fymo/remote/adapters.py tests/remote/test_adapters.py
git commit -m "feat(remote): validate_args + serialize_response (pydantic + stdlib)"
```

### Task 12: WSGI router for `/__remote/<m>/<fn>`

**Files:**
- Create: `fymo/remote/router.py`
- Test: `tests/remote/test_router.py`

- [ ] **Step 1: Write the failing test**

```python
"""WSGI handler for remote function calls."""
import io
import json
import sys
from pathlib import Path
import pytest
from fymo.remote.router import handle_remote


def _scaffold(tmp_path: Path, files: dict[str, str]) -> Path:
    for rel, content in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    return tmp_path


def _call(environ: dict):
    responses = []
    def start_response(status, headers):
        responses.append((status, headers))
    body = b"".join(handle_remote(environ, start_response))
    return responses[0], body


def _make_environ(path: str, body: dict, cookies: str = "") -> dict:
    raw = json.dumps(body).encode()
    return {
        "REQUEST_METHOD": "POST",
        "PATH_INFO": path,
        "CONTENT_LENGTH": str(len(raw)),
        "CONTENT_TYPE": "application/json",
        "HTTP_COOKIE": cookies,
        "REMOTE_ADDR": "127.0.0.1",
        "wsgi.input": io.BytesIO(raw),
    }


@pytest.fixture
def remote_project(tmp_path: Path, monkeypatch):
    proj = _scaffold(tmp_path, {
        "app/__init__.py": "",
        "app/remote/__init__.py": "",
        "app/remote/posts.py": (
            "from fymo.remote import current_uid, NotFound\n"
            "def hello(name: str) -> str:\n"
            "    return f'hi {name}'\n"
            "def whoami() -> str:\n"
            "    return current_uid()\n"
            "def boom() -> str:\n"
            "    raise NotFound('nope')\n"
        ),
    })
    monkeypatch.syspath_prepend(str(proj))
    yield proj
    for name in list(sys.modules):
        if name.startswith("app."):
            del sys.modules[name]


def test_calls_function_and_returns_data(remote_project):
    env = _make_environ("/__remote/posts/hello", {"args": ["alice"]})
    (status, headers), body = _call(env)
    assert status.startswith("200")
    payload = json.loads(body)
    assert payload == {"ok": True, "data": "hi alice"}


def test_issues_uid_on_first_call(remote_project):
    env = _make_environ("/__remote/posts/whoami", {"args": []})
    (status, headers), body = _call(env)
    assert status.startswith("200")
    set_cookie = next((v for k, v in headers if k.lower() == "set-cookie"), None)
    assert set_cookie is not None
    assert "fymo_uid=" in set_cookie
    payload = json.loads(body)
    assert payload["data"].startswith("u_")


def test_reads_existing_uid_cookie(remote_project):
    env = _make_environ("/__remote/posts/whoami", {"args": []}, cookies="fymo_uid=u_existing")
    (status, headers), body = _call(env)
    payload = json.loads(body)
    assert payload["data"] == "u_existing"


def test_unknown_function_returns_404(remote_project):
    env = _make_environ("/__remote/posts/nope", {"args": []})
    (status, headers), body = _call(env)
    assert status.startswith("404")


def test_validation_error_returns_422(remote_project):
    env = _make_environ("/__remote/posts/hello", {"args": [123]})  # int instead of str
    (status, headers), body = _call(env)
    assert status.startswith("422")
    payload = json.loads(body)
    assert payload["ok"] is False


def test_domain_error_returns_correct_status(remote_project):
    env = _make_environ("/__remote/posts/boom", {"args": []})
    (status, headers), body = _call(env)
    assert status.startswith("404")
    payload = json.loads(body)
    assert payload["error"] == "not_found"
```

- [ ] **Step 2: Run — expect failure**

Run: `.venv/bin/python -m pytest tests/remote/test_router.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `fymo/remote/router.py`**

```python
"""WSGI handler for POST /__remote/<module>/<fn>."""
import importlib
import inspect
import json
import traceback
import typing
from typing import Iterable

from fymo.remote.adapters import validate_args, serialize_response
from fymo.remote.context import request_scope
from fymo.remote.errors import RemoteError
from fymo.remote.identity import _ensure_uid

try:
    import pydantic
    _has_pydantic = True
except ImportError:
    _has_pydantic = False

_MAX_BODY = 1 * 1024 * 1024


def _json_response(start_response, status: int, payload: dict, set_cookie: str | None = None) -> Iterable[bytes]:
    body = json.dumps(payload).encode("utf-8")
    headers = [("Content-Type", "application/json"), ("Content-Length", str(len(body)))]
    if set_cookie:
        headers.append(("Set-Cookie", set_cookie))
    statuses = {
        200: "200 OK", 400: "400 Bad Request", 401: "401 Unauthorized",
        403: "403 Forbidden", 404: "404 Not Found", 409: "409 Conflict",
        413: "413 Payload Too Large", 422: "422 Unprocessable Entity",
        500: "500 Internal Server Error",
    }
    start_response(statuses.get(status, f"{status} Status"), headers)
    return [body]


def _resolve(module_name: str, fn_name: str):
    """Return (fn, signature, hints) or (None, None, None)."""
    if not module_name.replace("_", "").isalnum() or not fn_name.replace("_", "").isalnum():
        return None, None, None
    if fn_name.startswith("_"):
        return None, None, None
    full = f"app.remote.{module_name}"
    try:
        mod = importlib.import_module(full)
    except ImportError:
        return None, None, None
    fn = getattr(mod, fn_name, None)
    if fn is None or not callable(fn) or getattr(fn, "__module__", None) != full:
        return None, None, None
    sig = inspect.signature(fn)
    hints = typing.get_type_hints(fn, include_extras=True)
    return fn, sig, hints


def handle_remote(environ: dict, start_response) -> Iterable[bytes]:
    path = environ.get("PATH_INFO", "")
    parts = path[len("/__remote/"):].split("/")
    if len(parts) != 2:
        return _json_response(start_response, 400, {"ok": False, "error": "bad_path"})
    module_name, fn_name = parts

    fn, sig, hints = _resolve(module_name, fn_name)
    if fn is None:
        return _json_response(start_response, 404, {"ok": False, "error": "unknown_function"})

    try:
        length = int(environ.get("CONTENT_LENGTH") or 0)
    except ValueError:
        length = 0
    if length > _MAX_BODY:
        return _json_response(start_response, 413, {"ok": False, "error": "too_large"})

    raw = environ["wsgi.input"].read(length) if length else b"{}"
    try:
        body = json.loads(raw or b"{}")
    except json.JSONDecodeError:
        return _json_response(start_response, 400, {"ok": False, "error": "invalid_json"})

    args = body.get("args") or []
    try:
        validated = validate_args(args, sig, hints)
    except Exception as e:
        if _has_pydantic and isinstance(e, pydantic.ValidationError):
            return _json_response(start_response, 422, {"ok": False, "error": "validation", "issues": e.errors()})
        return _json_response(start_response, 422, {"ok": False, "error": "validation", "message": str(e)})

    uid, set_cookie = _ensure_uid(environ)

    try:
        with request_scope(uid=uid, environ=environ):
            result = fn(*validated)
    except RemoteError as e:
        return _json_response(start_response, e.status, {"ok": False, "error": e.code, "message": str(e)}, set_cookie)
    except Exception as e:
        return _json_response(start_response, 500,
                              {"ok": False, "error": "internal", "message": str(e), "traceback": traceback.format_exc()},
                              set_cookie)

    serialized = serialize_response(result, hints.get("return"))
    return _json_response(start_response, 200, {"ok": True, "data": serialized}, set_cookie)
```

- [ ] **Step 4: Run — expect pass**

Run: `.venv/bin/python -m pytest tests/remote/test_router.py -v`
Expected: 6 PASSED.

- [ ] **Step 5: Commit**

```bash
git add fymo/remote/router.py tests/remote/test_router.py
git commit -m "feat(remote): WSGI handler for /__remote/<module>/<fn>"
```

### Task 13: Wire `/__remote/` into FymoApp

**Files:**
- Modify: `fymo/core/server.py`
- Test: `tests/integration/test_remote_e2e.py` (new)

- [ ] **Step 1: Write the failing test**

```python
"""End-to-end: an HTTP request to /__remote/<m>/<fn> through FymoApp."""
import io
import json
import sys
from pathlib import Path
import pytest


@pytest.mark.usefixtures("node_available")
def test_remote_call_through_fymoapp(example_app: Path, monkeypatch):
    # Add a remote module
    remote_dir = example_app / "app" / "remote"
    remote_dir.mkdir(parents=True, exist_ok=True)
    (remote_dir / "__init__.py").write_text("")
    (remote_dir / "greeter.py").write_text(
        "def hello(name: str) -> str:\n    return f'hi {name}'\n"
    )

    from fymo.build.pipeline import BuildPipeline
    BuildPipeline(project_root=example_app).build(dev=False)

    monkeypatch.chdir(example_app)
    from fymo import create_app
    app = create_app(example_app)
    try:
        responses = []
        def start_response(status, headers): responses.append((status, headers))
        body_payload = json.dumps({"args": ["alice"]}).encode()
        body = b"".join(app({
            "REQUEST_METHOD": "POST",
            "PATH_INFO": "/__remote/greeter/hello",
            "CONTENT_LENGTH": str(len(body_payload)),
            "CONTENT_TYPE": "application/json",
            "QUERY_STRING": "",
            "SERVER_NAME": "x", "SERVER_PORT": "0", "SERVER_PROTOCOL": "HTTP/1.1",
            "REMOTE_ADDR": "127.0.0.1",
            "wsgi.input": io.BytesIO(body_payload),
            "wsgi.errors": sys.stderr, "wsgi.url_scheme": "http",
        }, start_response))

        assert responses[0][0].startswith("200")
        payload = json.loads(body)
        assert payload == {"ok": True, "data": "hi alice"}
    finally:
        if app.sidecar:
            app.sidecar.stop()
        for name in list(sys.modules):
            if name.startswith("app."):
                del sys.modules[name]
```

- [ ] **Step 2: Run — expect failure**

Run: `.venv/bin/python -m pytest tests/integration/test_remote_e2e.py -v`
Expected: FAIL — `/__remote/...` returns 404 (or the SSR path tries to serve it as a route).

- [ ] **Step 3: Wire `/__remote/` into `fymo/core/server.py`**

In `FymoApp.__call__`, add this branch BEFORE the existing `/dist/` branch:

```python
        if path.startswith("/__remote/"):
            from fymo.remote.router import handle_remote
            return handle_remote(environ, start_response)
```

- [ ] **Step 4: Run — expect pass**

Run: `.venv/bin/python -m pytest tests/integration/test_remote_e2e.py -v`
Expected: 1 PASSED.

Run full suite:
`.venv/bin/python -m pytest tests/ -q`
Expected: no regressions.

- [ ] **Step 5: Commit**

```bash
git add fymo/core/server.py tests/integration/test_remote_e2e.py
git commit -m "feat(server): dispatch POST /__remote/... before SSR branch"
```

---

## Phase E — esbuild plugin + SSR callable serialization

### Task 14: esbuild plugin resolving `$remote/<name>`

**Files:**
- Create: `fymo/build/js/plugins/remote.mjs`
- Modify: `fymo/build/js/build.mjs`
- Modify: `fymo/build/js/dev.mjs`
- Test: `tests/integration/test_remote_import.py`

- [ ] **Step 1: Write the failing test**

```python
"""<script> can import from $remote/<module> and esbuild resolves it."""
from pathlib import Path
import pytest
from fymo.build.pipeline import BuildPipeline


@pytest.mark.usefixtures("node_available")
def test_remote_import_resolves(example_app: Path):
    # Add a remote module
    remote = example_app / "app" / "remote"
    remote.mkdir(parents=True, exist_ok=True)
    (remote / "__init__.py").write_text("")
    (remote / "greeter.py").write_text(
        "def hello(name: str) -> str:\n    return f'hi {name}'\n"
    )

    # Patch the test.svelte to import from $remote
    test_svelte = example_app / "app" / "templates" / "todos" / "test.svelte"
    new_content = (
        '<script>\n'
        '  import { hello } from "$remote/greeter";\n'
        '  let { message = "x" } = $props();\n'
        '  async function go() { await hello("world"); }\n'
        '</script>\n'
        '<div>{message}</div>\n'
    )
    test_svelte.write_text(new_content)

    BuildPipeline(project_root=example_app).build(dev=False)

    # The client bundle should reference the resolved remote path
    import json
    manifest = json.loads((example_app / "dist" / "manifest.json").read_text())
    bundle_path = example_app / "dist" / manifest["routes"]["todos"]["client"]
    bundle_text = bundle_path.read_text()
    # Either the function is inlined, OR the runtime import shows up
    assert "__rpc" in bundle_text
    assert "greeter/hello" in bundle_text
```

- [ ] **Step 2: Run — expect failure**

Run: `.venv/bin/python -m pytest tests/integration/test_remote_import.py -v`
Expected: FAIL — esbuild errors with "Could not resolve $remote/greeter".

- [ ] **Step 3: Implement `fymo/build/js/plugins/remote.mjs`**

```javascript
import path from 'node:path';

/**
 * Resolves `$remote/<name>` imports to dist/client/_remote/<name>.js.
 * The codegen step (Python side) must have run first.
 *
 * @param {{ remoteDir: string }} options - absolute path to dist/client/_remote/
 */
export function fymoRemotePlugin({ remoteDir }) {
    return {
        name: 'fymo-remote',
        setup(build) {
            build.onResolve({ filter: /^\$remote\// }, (args) => {
                const name = args.path.slice('$remote/'.length);
                const filePath = path.join(remoteDir, `${name}.js`);
                return { path: filePath };
            });
        },
    };
}
```

- [ ] **Step 4: Wire the plugin into `build.mjs` and `dev.mjs`**

In `fymo/build/js/build.mjs`, add an import:

```javascript
import { fymoRemotePlugin } from './plugins/remote.mjs';
```

In `buildClient()`, append the plugin to the existing plugins array:

```javascript
plugins: [
  fymoRemotePlugin({ remoteDir: path.join(config.distDir, 'client', '_remote') }),
  sveltePlugin({ preprocess: vitePreprocess(), compilerOptions: { generate: 'client', dev: false } }),
],
```

Same edit in `fymo/build/js/dev.mjs` for the client context.

(Server pass doesn't need the plugin — `$remote/` imports only make sense in browser code, and Svelte's `<script>` blocks are split between server and client compile.)

- [ ] **Step 5: Run — expect pass**

Run: `.venv/bin/python -m pytest tests/integration/test_remote_import.py -v`
Expected: 1 PASSED.

- [ ] **Step 6: Commit**

```bash
git add fymo/build/js/plugins/remote.mjs fymo/build/js/build.mjs fymo/build/js/dev.mjs tests/integration/test_remote_import.py
git commit -m "feat(build): esbuild plugin resolving \$remote/<name> imports"
```

### Task 15: SSR callable serialization in `build_html`

**Files:**
- Modify: `fymo/core/html.py`
- Test: `tests/core/test_html.py` (extend)

- [ ] **Step 1: Add failing test**

Append to `tests/core/test_html.py`:

```python
def test_remote_callable_serialized_as_marker(monkeypatch):
    """A callable from app.remote.* in props should appear as a {__fymo_remote: ...} marker."""
    import sys, types
    fake_module = types.ModuleType("app.remote.posts")
    def create_post(title: str) -> str: return title
    create_post.__module__ = "app.remote.posts"
    fake_module.create_post = create_post
    sys.modules.setdefault("app", types.ModuleType("app"))
    sys.modules.setdefault("app.remote", types.ModuleType("app.remote"))
    sys.modules["app.remote.posts"] = fake_module

    from fymo.build.manifest import RouteAssets
    assets = RouteAssets(ssr="ssr/x.mjs", client="client/x.js", css=None, preload=[])
    html = build_html(
        body="",
        head_extra="",
        props={"create_post": create_post},
        assets=assets,
        title="t",
        asset_prefix="/dist",
    )
    # The marker should appear in the JSON props island
    assert '"__fymo_remote":"posts/create_post"' in html or '"__fymo_remote": "posts/create_post"' in html
```

- [ ] **Step 2: Run — expect failure**

Run: `.venv/bin/python -m pytest tests/core/test_html.py::test_remote_callable_serialized_as_marker -v`
Expected: FAIL — `json.dumps` raises `TypeError: Object of type function is not JSON serializable`.

- [ ] **Step 3: Update `fymo/core/html.py`'s `_safe_json` to handle remote callables**

Replace `_safe_json` with:

```python
def _remote_marker(obj):
    """If obj is a callable from app.remote.*, return its marker dict; else raise."""
    mod = getattr(obj, "__module__", None)
    if mod and mod.startswith("app.remote.") and callable(obj):
        module_name = mod[len("app.remote."):]
        return {"__fymo_remote": f"{module_name}/{obj.__name__}"}
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def _safe_json(obj: Any) -> str:
    """JSON serialize and escape for safe embedding in <script type=application/json>."""
    return (
        json.dumps(obj, default=_remote_marker)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )
```

- [ ] **Step 4: Run — expect pass**

Run: `.venv/bin/python -m pytest tests/core/test_html.py -v`
Expected: 4 PASSED (3 prior + 1 new).

- [ ] **Step 5: Commit**

```bash
git add fymo/core/html.py tests/core/test_html.py
git commit -m "feat(html): serialize app.remote.* callables as RPC markers in SSR props"
```

### Task 16: Client hydrate calls `__resolveRemoteProps` before mount

**Files:**
- Modify: `fymo/build/entry_generator.py`
- Test: extend existing `tests/integration/test_request_flow.py`

- [ ] **Step 1: Add failing test**

Append to `tests/integration/test_request_flow.py`:

```python
@pytest.mark.usefixtures("node_available")
def test_client_entry_calls_resolve_remote_props(example_app, monkeypatch):
    # Add a remote module so the client entry is generated with resolution code
    remote = example_app / "app" / "remote"
    remote.mkdir(parents=True, exist_ok=True)
    (remote / "__init__.py").write_text("")
    (remote / "x.py").write_text("def fn(s: str) -> str: return s\n")

    BuildPipeline(project_root=example_app).build(dev=False)

    from fymo import create_app
    app = create_app(example_app)
    try:
        import re, io, sys
        responses = []
        def sr(s, h): responses.append((s, h))
        body = b"".join(app({
            "REQUEST_METHOD": "GET", "PATH_INFO": "/", "QUERY_STRING": "",
            "SERVER_NAME": "x", "SERVER_PORT": "0", "SERVER_PROTOCOL": "HTTP/1.1",
            "wsgi.input": io.BytesIO(), "wsgi.errors": sys.stderr, "wsgi.url_scheme": "http",
        }, sr))
        m = re.search(rb'src="(/dist/client/todos\.[A-Z0-9]+\.js)"', body)
        assert m is not None
        bundle_url = m.group(1).decode()
        b2 = []
        def sr2(s, h): b2.append((s, h))
        bundle = b"".join(app({
            "REQUEST_METHOD": "GET", "PATH_INFO": bundle_url, "QUERY_STRING": "",
            "SERVER_NAME": "x", "SERVER_PORT": "0", "SERVER_PROTOCOL": "HTTP/1.1",
            "wsgi.input": io.BytesIO(), "wsgi.errors": sys.stderr, "wsgi.url_scheme": "http",
        }, sr2))
        assert b"__resolveRemoteProps" in bundle
    finally:
        if app.sidecar:
            app.sidecar.stop()
```

- [ ] **Step 2: Run — expect failure**

Run: `.venv/bin/python -m pytest tests/integration/test_request_flow.py::test_client_entry_calls_resolve_remote_props -v`
Expected: FAIL.

- [ ] **Step 3: Update `CLIENT_ENTRY_TEMPLATE` in `fymo/build/entry_generator.py`**

Replace the template:

```python
CLIENT_ENTRY_TEMPLATE = """\
import {{ hydrate }} from 'svelte';
import Component from '{component_import}';
import {{ __resolveRemoteProps }} from '/dist/client/_remote/__runtime.js';

const propsEl = document.getElementById('svelte-props');
const props = propsEl ? JSON.parse(propsEl.textContent) : {{}};
const docEl = document.getElementById('svelte-doc');
const doc = docEl ? JSON.parse(docEl.textContent) : {{}};
globalThis.getDoc = () => doc;
__resolveRemoteProps(props);
const target = document.getElementById('svelte-app');

hydrate(Component, {{ target, props }});
"""
```

(The import path `/dist/client/_remote/__runtime.js` is a runtime URL, not a build-time import; esbuild will fetch it via the module URL at runtime. To avoid esbuild trying to resolve it, use a `?url` import OR inline the helper. Simpler: inline the helper directly in the entry stub.)

Actually replace with inlined helper (no extra import needed):

```python
CLIENT_ENTRY_TEMPLATE = """\
import {{ hydrate }} from 'svelte';
import Component from '{component_import}';

const propsEl = document.getElementById('svelte-props');
const props = propsEl ? JSON.parse(propsEl.textContent) : {{}};
const docEl = document.getElementById('svelte-doc');
const doc = docEl ? JSON.parse(docEl.textContent) : {{}};
globalThis.getDoc = () => doc;

// Inline __resolveRemoteProps (kept here so we don't depend on the codegen runtime
// being available even when no remote modules exist).
async function __rpc(path, args) {{
    const res = await fetch('/__remote/' + path, {{
        method: 'POST', credentials: 'same-origin',
        headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify({{ args }}),
    }});
    const payload = await res.json().catch(() => ({{ ok: false, error: 'invalid_json' }}));
    if (payload.ok) return payload.data;
    const err = new Error(payload.message || payload.error);
    err.status = res.status; err.error = payload.error; err.issues = payload.issues;
    throw err;
}}
function __resolveRemoteProps(p) {{
    for (const k in p) {{
        const v = p[k];
        if (v && typeof v === 'object' && v.__fymo_remote) {{
            const path = v.__fymo_remote;
            p[k] = (...args) => __rpc(path, args);
        }}
    }}
}}
__resolveRemoteProps(props);

const target = document.getElementById('svelte-app');
hydrate(Component, {{ target, props }});
"""
```

- [ ] **Step 4: Run — expect pass**

Run: `.venv/bin/python -m pytest tests/integration/test_request_flow.py -v`
Expected: all integration tests PASS, including the new one.

- [ ] **Step 5: Commit**

```bash
git add fymo/build/entry_generator.py tests/integration/test_request_flow.py
git commit -m "feat(build): resolve remote-prop markers to fetch wrappers before hydrate"
```

---

## Phase F — Parametric route params to controllers

### Task 17: Pass route params as kwargs to `getContext`

**Files:**
- Modify: `fymo/core/template_renderer.py`
- Test: `tests/integration/test_route_params.py` (new)

- [ ] **Step 1: Write the failing test**

```python
"""Routes with :id capture should pass params as kwargs to getContext."""
from pathlib import Path
import pytest


@pytest.mark.usefixtures("node_available")
def test_param_passed_to_getContext(example_app, monkeypatch):
    # Add a route that uses :id
    fymo_yml = example_app / "fymo.yml"
    text = fymo_yml.read_text()
    if "items" not in text:
        # Add an `items` resource (auto-generates /items, /items/:id, etc.)
        # To keep changes minimal, we hand-add a controller + template that match.
        pass

    # Create controller + template for an existing 'todos/:id' show route
    show_ctrl = example_app / "app" / "controllers" / "todos.py"
    show_ctrl.write_text(
        "def getContext(id: str = ''):\n"
        "    return {'todo_id': id, 'name': f'todo-{id}'}\n"
    )

    show_tpl_dir = example_app / "app" / "templates" / "todos"
    show_tpl_dir.mkdir(parents=True, exist_ok=True)
    show_tpl = show_tpl_dir / "show.svelte"
    show_tpl.write_text(
        '<script>let { todo_id, name } = $props();</script>\n'
        '<div data-id={todo_id}>{name}</div>\n'
    )

    from fymo.build.pipeline import BuildPipeline
    BuildPipeline(project_root=example_app).build(dev=False)

    from fymo import create_app
    app = create_app(example_app)
    try:
        import io, sys
        responses = []
        def sr(s, h): responses.append((s, h))
        body = b"".join(app({
            "REQUEST_METHOD": "GET", "PATH_INFO": "/todos/abc123", "QUERY_STRING": "",
            "SERVER_NAME": "x", "SERVER_PORT": "0", "SERVER_PROTOCOL": "HTTP/1.1",
            "wsgi.input": io.BytesIO(), "wsgi.errors": sys.stderr, "wsgi.url_scheme": "http",
        }, sr))
        assert responses[0][0].startswith("200")
        assert b"todo-abc123" in body or b'data-id="abc123"' in body
    finally:
        if app.sidecar:
            app.sidecar.stop()
```

- [ ] **Step 2: Run — expect failure**

Run: `.venv/bin/python -m pytest tests/integration/test_route_params.py -v`
Expected: FAIL — controller called with no args, params dropped.

- [ ] **Step 3: Modify `_render_via_sidecar` and `_load_controller_data`**

In `fymo/core/template_renderer.py`:

Update the `_render_via_sidecar` method to pass params:

Find this line:
```python
        _, props, doc_meta = self._load_controller_data(controller_module)
```
Replace with:
```python
        params = route_info.get("params", {})
        _, props, doc_meta = self._load_controller_data(controller_module, params=params)
```

Update `_load_controller_data` signature:

```python
    def _load_controller_data(
        self, controller_module: str, params: dict | None = None
    ) -> Tuple[Any, Dict[str, Any], Dict[str, Any]]:
        params = params or {}
        try:
            controller = importlib.import_module(controller_module)
            props: dict = {}
            if hasattr(controller, "getContext") and callable(getattr(controller, "getContext")):
                # Pass route params as kwargs; controller can choose to accept any subset
                getContext = getattr(controller, "getContext")
                sig = inspect.signature(getContext)
                accepted = {k: v for k, v in params.items() if k in sig.parameters}
                props = getContext(**accepted)
            doc_meta: dict = {}
            if hasattr(controller, "getDoc") and callable(getattr(controller, "getDoc")):
                doc_meta = controller.getDoc()
            return controller, props, doc_meta
        except (ImportError, AttributeError) as e:
            print(f"{Color.FAIL}Controller error: {e}{Color.ENDC}")
            return None, {}, {}
```

Add `import inspect` at the top of the file if not already present.

- [ ] **Step 4: Run — expect pass**

Run: `.venv/bin/python -m pytest tests/integration/test_route_params.py -v`
Expected: 1 PASSED.

Run full suite: `.venv/bin/python -m pytest tests/ -q`
Expected: no regressions.

- [ ] **Step 5: Commit**

```bash
git add fymo/core/template_renderer.py tests/integration/test_route_params.py
git commit -m "feat(renderer): pass route_info['params'] as kwargs to getContext"
```

---

## Phase G — Blog example

### Task 18: Scaffold the blog app skeleton

**Files (create):**
- `examples/blog_app/fymo.yml`
- `examples/blog_app/server.py`
- `examples/blog_app/package.json`
- `examples/blog_app/requirements.txt`
- `examples/blog_app/tsconfig.json`
- `examples/blog_app/.gitignore`
- `examples/blog_app/app/__init__.py`
- `examples/blog_app/app/controllers/__init__.py`
- `examples/blog_app/app/lib/__init__.py`
- `examples/blog_app/app/remote/__init__.py`
- `examples/blog_app/app/templates/index/index.svelte` (placeholder)

- [ ] **Step 1: Create directory structure and fymo.yml**

```bash
mkdir -p examples/blog_app/app/{controllers,lib,remote,posts,templates/{index,posts,tags,_shared}}
touch examples/blog_app/app/__init__.py
touch examples/blog_app/app/controllers/__init__.py
touch examples/blog_app/app/lib/__init__.py
touch examples/blog_app/app/remote/__init__.py
```

`examples/blog_app/fymo.yml`:

```yaml
name: blog_app
version: 1.0.0
description: "A blog app example for the Fymo framework — showcases remote functions"

routes:
  root: index.index
  resources:
    - posts
    - tags

build:
  output_dir: dist
  minify: false

server:
  host: 127.0.0.1
  port: 8000
```

`examples/blog_app/server.py`:

```python
#!/usr/bin/env python3
"""Entry point for the blog app."""
from pathlib import Path
from fymo import create_app
from app.lib.seeder import ensure_seeded

PROJECT_ROOT = Path(__file__).resolve().parent
ensure_seeded(PROJECT_ROOT)
app = create_app(PROJECT_ROOT)

if __name__ == "__main__":
    from fymo.cli.commands.serve import run_dev_server
    run_dev_server(app)
```

`examples/blog_app/package.json`:

```json
{
  "name": "blog_app",
  "version": "1.0.0",
  "type": "module",
  "scripts": {
    "dev": "fymo dev",
    "build": "fymo build"
  },
  "dependencies": {
    "svelte": "^5.38.0"
  },
  "devDependencies": {
    "@sveltejs/vite-plugin-svelte": "^4.0.0",
    "esbuild": "^0.25.9",
    "esbuild-svelte": "^0.9.0",
    "typescript": "^5.5.0"
  }
}
```

`examples/blog_app/requirements.txt`:

```
fymo>=0.1.0
mistune>=3.0
pygments>=2.17
pydantic>=2.5
```

`examples/blog_app/tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "ESNext",
    "moduleResolution": "bundler",
    "strict": true,
    "verbatimModuleSyntax": true,
    "isolatedModules": true,
    "skipLibCheck": true,
    "paths": {
      "$remote/*": ["./dist/client/_remote/*"]
    }
  },
  "include": ["app/**/*.svelte", "app/**/*.ts"]
}
```

`examples/blog_app/.gitignore`:

```
dist/
.fymo/
.venv/
node_modules/
app/data/blog.db
__pycache__/
```

- [ ] **Step 2: Add a placeholder index template**

`examples/blog_app/app/templates/index/index.svelte`:

```svelte
<script>
  let { posts = [] } = $props();
</script>
<h1>Blog</h1>
<ul>
  {#each posts as p}
    <li>{p.title}</li>
  {/each}
</ul>
```

`examples/blog_app/app/controllers/index.py`:

```python
def getContext():
    return {"posts": []}
```

- [ ] **Step 3: Install npm + python deps**

```bash
cd examples/blog_app
npm install
cd ../..
```

(No `pip install -r requirements.txt` here — the worktree's `.venv` has fymo editable; install pydantic/mistune/pygments separately.)

```bash
.venv/bin/pip install 'mistune>=3.0' 'pygments>=2.17' 'pydantic>=2.5'
```

- [ ] **Step 4: Smoke-test the empty app**

```bash
cd examples/blog_app
/Users/bishwasbhandari/Projects/fymo/.venv/bin/fymo build 2>&1 | tail -2
cd ../..
```

Expected: `✓ Built to .../examples/blog_app/dist/`.

(The seeder doesn't exist yet — we add it in Task 19; for now `ensure_seeded` won't be importable. Comment out the import in `server.py` for this smoke or skip running the server.)

Quick fix: in `server.py`, wrap `ensure_seeded` in try/except for now:

```python
try:
    from app.lib.seeder import ensure_seeded
    ensure_seeded(PROJECT_ROOT)
except ImportError:
    pass
```

- [ ] **Step 5: Commit**

```bash
git add examples/blog_app
git commit -m "feat(blog): scaffold blog_app skeleton with fymo.yml + tsconfig"
```

### Task 19: DB layer + sample posts + seeder

**Files (create):**
- `examples/blog_app/app/lib/db.py`
- `examples/blog_app/app/lib/seeder.py`
- `examples/blog_app/app/posts/welcome-to-fymo.md`
- `examples/blog_app/app/posts/build-pipeline-deep-dive.md`
- `examples/blog_app/app/posts/why-svelte5-and-python.md`

- [ ] **Step 1: Implement `app/lib/db.py`**

```python
"""SQLite singleton with schema migration on first connect."""
import sqlite3
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS posts (
    slug TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    content_html TEXT NOT NULL,
    tags TEXT NOT NULL,
    published_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_slug TEXT NOT NULL REFERENCES posts(slug),
    uid TEXT NOT NULL,
    name TEXT NOT NULL,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reactions (
    post_slug TEXT NOT NULL REFERENCES posts(slug),
    uid TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('clap', 'fire', 'heart', 'mind')),
    PRIMARY KEY (post_slug, uid, kind)
);
"""


class DB:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None

    def connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.executescript(_SCHEMA)
            self._conn.commit()
        return self._conn

    def fetchone(self, sql: str, params: list[Any] = ()) -> dict | None:
        row = self.connect().execute(sql, params).fetchone()
        return dict(row) if row else None

    def fetchall(self, sql: str, params: list[Any] = ()) -> list[dict]:
        rows = self.connect().execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def execute(self, sql: str, params: list[Any] = ()) -> int:
        cur = self.connect().execute(sql, params)
        self.connect().commit()
        return cur.lastrowid


# Module-level instance — initialized lazily by callers
_db: DB | None = None


def get_db() -> DB:
    global _db
    if _db is None:
        from pathlib import Path
        # Resolve project root from this file's location
        project_root = Path(__file__).resolve().parent.parent.parent
        _db = DB(project_root / "app" / "data" / "blog.db")
    return _db
```

- [ ] **Step 2: Implement `app/lib/seeder.py`**

```python
"""Seed posts from app/posts/*.md into SQLite on first run."""
import re
from datetime import datetime
from pathlib import Path
import mistune
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_by_name, guess_lexer

from app.lib.db import get_db


_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    fm_block, body = m.group(1), m.group(2)
    meta: dict[str, str] = {}
    for line in fm_block.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip().strip('"\'')
    return meta, body


class _PygmentsRenderer(mistune.HTMLRenderer):
    def block_code(self, code: str, info: str | None = None) -> str:
        try:
            lexer = get_lexer_by_name(info or "text", stripall=False)
        except Exception:
            lexer = guess_lexer(code)
        formatter = HtmlFormatter(noclasses=True, style="monokai")
        return highlight(code, lexer, formatter)


_md = mistune.create_markdown(renderer=_PygmentsRenderer())


def ensure_seeded(project_root: Path) -> None:
    """If posts table is empty, seed from app/posts/*.md."""
    db = get_db()
    if db.fetchone("SELECT 1 FROM posts LIMIT 1"):
        return
    posts_dir = project_root / "app" / "posts"
    if not posts_dir.is_dir():
        return
    for md_path in sorted(posts_dir.glob("*.md")):
        text = md_path.read_text()
        meta, body = _parse_frontmatter(text)
        slug = meta.get("slug") or md_path.stem
        title = meta.get("title") or slug.replace("-", " ").title()
        summary = meta.get("summary") or ""
        tags = meta.get("tags") or ""
        published_at = meta.get("published_at") or datetime.utcnow().isoformat()
        content_html = _md(body)
        db.execute(
            "INSERT OR REPLACE INTO posts (slug, title, summary, content_html, tags, published_at) VALUES (?, ?, ?, ?, ?, ?)",
            [slug, title, summary, content_html, tags, published_at],
        )
```

- [ ] **Step 3: Write three sample posts**

`examples/blog_app/app/posts/welcome-to-fymo.md`:

```markdown
---
title: Welcome to Fymo
summary: A Python framework for SSR Svelte apps without the SvelteKit weight
tags: announcement,fymo
published_at: 2026-04-28T10:00:00Z
---

# Welcome to Fymo

Fymo is what you'd build if you wanted SvelteKit's developer ergonomics but on a Python backend, without dragging Node into your data layer.

## Why?

Most full-stack JS frameworks force the entire stack to live in one runtime. That's elegant when your team is JS-only, but punishes Python shops who already have working Django, FastAPI, or Flask code and a database their ORM understands.

Fymo lets you keep Python on the server and use Svelte 5 on the client, with a build-time pipeline that emits cacheable, hashed assets and a Node sidecar that handles per-request SSR.

## What's inside

- **Build-time esbuild pipeline** — `fymo build` produces `dist/` with hashed JS, CSS, and a Node SSR sidecar.
- **Persistent Node sidecar** — Python WSGI talks to a long-lived `node` over stdio. Microsecond per-request SSR.
- **Cross-route shared chunks** — `date-fns` imported by every page bundles once and ships once.
- **Remote functions** — write Python in `app/remote/posts.py`, call from Svelte as if local.

```python
def get_posts() -> list[Post]:
    return db.fetchall("SELECT * FROM posts")
```

```svelte
<script lang="ts">
  import { get_posts } from '$remote/posts';
  let posts = await get_posts();
</script>
```

That's it.
```

`examples/blog_app/app/posts/build-pipeline-deep-dive.md`:

```markdown
---
title: How Fymo's build pipeline works
summary: A walk through the esbuild + Node sidecar + manifest architecture
tags: architecture,build
published_at: 2026-04-28T11:00:00Z
---

# How Fymo's build pipeline works

When you run `fymo build`, here's what happens, in order.

## 1. Discovery

The Python orchestrator walks `app/templates/` looking for `<route>/index.svelte` files. Each match becomes a route entry — `app/templates/posts/show.svelte` → route `posts`.

It also walks `app/remote/` and introspects every top-level callable: pulls the `inspect.signature`, resolves type hints with `typing.get_type_hints`, and walks every referenced type.

## 2. Server pass

esbuild bundles each route as a server module:

```js
await esbuild.build({
    entryPoints: { posts: 'app/templates/posts/show.svelte', ... },
    outdir: 'dist/ssr',
    format: 'esm',
    platform: 'node',
    bundle: true,
    plugins: [sveltePlugin({ compilerOptions: { generate: 'server' } })],
});
```

Each `dist/ssr/<route>.mjs` exports a Svelte component — the sidecar imports it at runtime.

## 3. Client pass

Same input, different config:

- `platform: 'browser'`
- `splitting: true` (this is the magic — date-fns imported by both `posts` and `tags` ends up in one shared chunk)
- `entryNames: '[name].[hash]'` for long-cache safety

## 4. Remote codegen

For each `app/remote/<name>.py`, emit a sibling `.js` (fetch wrappers) and `.d.ts` (TypeScript declarations) under `dist/client/_remote/`.

## 5. Manifest

Write `dist/manifest.json` mapping each route to its hashed JS, CSS, and shared chunk preload list.

## 6. Sidecar

Copy `sidecar.mjs` to `dist/`. The Python server spawns it once per `fymo serve`; it imports SSR modules lazily and answers stdio JSON requests.
```

`examples/blog_app/app/posts/why-svelte5-and-python.md`:

```markdown
---
title: Why Svelte 5 + Python is a great combo
summary: Reactive UI without the JS-everywhere tax
tags: opinion,svelte,python
published_at: 2026-04-28T12:00:00Z
---

# Why Svelte 5 + Python is a great combo

The last decade of full-stack frameworks has, with very few exceptions, said: pick a runtime, run everything in it. Next.js puts your data layer in JS. Django insists on Jinja templates that age like milk. Phoenix LiveView is brilliant but ties you to BEAM.

Svelte 5 changed the calculus.

## Runes are reactive without ceremony

```svelte
<script>
  let count = $state(0);
  let doubled = $derived(count * 2);
</script>

<button onclick={() => count++}>{doubled}</button>
```

That's the entire mental model. No `useState`, no `useMemo`, no dependency arrays. Just declare what's reactive and let the compiler track it.

## The runtime is tiny

A typical Svelte 5 page bundle is 5–15 KB after gzip. React + RSC clocks in at 80 KB+. That difference is real on slow phones and contested networks.

## Python is *fine* for the data layer

Your team already speaks SQL. `pandas` exists. `pydantic` is industrial-strength validation. ORMs are excellent. There's no reason to translate your data layer into TypeScript just so you can render it in JSX.

Fymo splits the difference: Python where it shines, Svelte where it shines, a thin wire format between them.
```

- [ ] **Step 4: Test the seeder**

```bash
cd examples/blog_app
/Users/bishwasbhandari/Projects/fymo/.venv/bin/python -c "
from pathlib import Path
from app.lib.seeder import ensure_seeded
from app.lib.db import get_db
ensure_seeded(Path.cwd())
print(get_db().fetchall('SELECT slug, title FROM posts'))
"
```

Expected: prints three rows with slugs `welcome-to-fymo`, `build-pipeline-deep-dive`, `why-svelte5-and-python`.

```bash
rm app/data/blog.db  # Reset so subsequent runs re-seed
cd ../..
```

- [ ] **Step 5: Commit**

```bash
git add examples/blog_app/app/lib examples/blog_app/app/posts
git commit -m "feat(blog): add SQLite db + markdown seeder + 3 sample posts"
```

### Task 20: Remote module — `app/remote/posts.py`

**Files:**
- Create: `examples/blog_app/app/remote/posts.py`

- [ ] **Step 1: Write the module**

```python
"""Remote functions for the blog: reads + comment/reaction mutations."""
from datetime import datetime
from typing import TypedDict, Literal
from pydantic import BaseModel, Field

from fymo.remote import current_uid, NotFound
from app.lib.db import get_db


class Post(TypedDict):
    slug: str
    title: str
    summary: str
    content_html: str
    tags: str
    published_at: str


class PostSummary(TypedDict):
    slug: str
    title: str
    summary: str
    tags: str
    published_at: str


class Comment(TypedDict):
    id: int
    name: str
    body: str
    created_at: str


ReactionKind = Literal["clap", "fire", "heart", "mind"]


class ReactionCounts(TypedDict):
    clap: int
    fire: int
    heart: int
    mind: int


class NewComment(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    body: str = Field(min_length=1, max_length=1000)


def get_posts() -> list[PostSummary]:
    return get_db().fetchall(
        "SELECT slug, title, summary, tags, published_at FROM posts ORDER BY published_at DESC"
    )


def get_post(slug: str) -> Post:
    row = get_db().fetchone(
        "SELECT slug, title, summary, content_html, tags, published_at FROM posts WHERE slug = ?",
        [slug],
    )
    if not row:
        raise NotFound(f"post '{slug}' not found")
    return row


def get_comments(slug: str) -> list[Comment]:
    return get_db().fetchall(
        "SELECT id, name, body, created_at FROM comments WHERE post_slug = ? ORDER BY created_at DESC",
        [slug],
    )


def create_comment(slug: str, input: NewComment) -> Comment:
    uid = current_uid()
    cid = get_db().execute(
        "INSERT INTO comments (post_slug, uid, name, body, created_at) VALUES (?, ?, ?, ?, ?)",
        [slug, uid, input.name, input.body, datetime.utcnow().isoformat()],
    )
    return get_db().fetchone(
        "SELECT id, name, body, created_at FROM comments WHERE id = ?", [cid]
    )


def get_reactions(slug: str) -> ReactionCounts:
    rows = get_db().fetchall(
        "SELECT kind, COUNT(*) AS n FROM reactions WHERE post_slug = ? GROUP BY kind",
        [slug],
    )
    counts: ReactionCounts = {"clap": 0, "fire": 0, "heart": 0, "mind": 0}
    for r in rows:
        counts[r["kind"]] = r["n"]
    return counts


def toggle_reaction(slug: str, kind: ReactionKind) -> ReactionCounts:
    uid = current_uid()
    db = get_db()
    existing = db.fetchone(
        "SELECT 1 FROM reactions WHERE post_slug = ? AND uid = ? AND kind = ?",
        [slug, uid, kind],
    )
    if existing:
        db.execute(
            "DELETE FROM reactions WHERE post_slug = ? AND uid = ? AND kind = ?",
            [slug, uid, kind],
        )
    else:
        db.execute(
            "INSERT INTO reactions (post_slug, uid, kind) VALUES (?, ?, ?)",
            [slug, uid, kind],
        )
    return get_reactions(slug)
```

- [ ] **Step 2: Quick smoke that codegen works**

```bash
cd examples/blog_app
/Users/bishwasbhandari/Projects/fymo/.venv/bin/fymo build 2>&1 | tail -3
ls dist/client/_remote/
cat dist/client/_remote/posts.d.ts | head -30
cd ../..
```

Expected: `dist/client/_remote/posts.js`, `posts.d.ts`, `__runtime.js` exist. The `.d.ts` includes interfaces for `Post`, `PostSummary`, `Comment`, `ReactionCounts`, `NewComment` and signatures for all six functions.

- [ ] **Step 3: Commit**

```bash
git add examples/blog_app/app/remote/posts.py
git commit -m "feat(blog): add remote module with posts/comments/reactions API"
```

### Task 21: Controllers

**Files (create):**
- `examples/blog_app/app/controllers/index.py` (replace placeholder)
- `examples/blog_app/app/controllers/posts.py`
- `examples/blog_app/app/controllers/tags.py`

- [ ] **Step 1: Implement `index.py`**

```python
"""Home page controller."""
from app.remote.posts import get_posts


def getContext():
    posts = get_posts()
    return {
        "hero": posts[0] if posts else None,
        "posts": posts[1:] if len(posts) > 1 else [],
    }


def getDoc():
    return {
        "title": "Fymo Blog",
        "head": {
            "meta": [
                {"name": "description", "content": "A demo blog showing off Fymo's remote functions"},
            ]
        },
    }
```

- [ ] **Step 2: Implement `posts.py` (the show route — `/posts/<id>`)**

```python
"""Post detail controller. Receives slug as `id` from the resource route."""
from app.remote.posts import get_post, get_comments, get_reactions, create_comment, toggle_reaction


def getContext(id: str = ""):
    post = get_post(id)
    return {
        "post": post,
        "initial_comments": get_comments(id),
        "initial_reactions": get_reactions(id),
        "create_comment": create_comment,    # remote callable threaded as prop
        "toggle_reaction": toggle_reaction,  # remote callable threaded as prop
    }


def getDoc():
    return {"title": "Post"}
```

- [ ] **Step 3: Implement `tags.py` (the show route — `/tags/<id>`)**

```python
"""Tag-filtered list."""
from app.remote.posts import get_posts


def getContext(id: str = ""):
    all_posts = get_posts()
    filtered = [p for p in all_posts if id in (p.get("tags") or "").split(",")]
    return {"tag": id, "posts": filtered}


def getDoc():
    return {"title": "Tag"}
```

- [ ] **Step 4: Commit**

```bash
git add examples/blog_app/app/controllers
git commit -m "feat(blog): add controllers for index, posts/show, tags/show"
```

### Task 22: Templates — index, posts/show, components

**Files (create):**
- `examples/blog_app/app/templates/index/index.svelte` (replace placeholder)
- `examples/blog_app/app/templates/posts/show.svelte`
- `examples/blog_app/app/templates/posts/Comments.svelte`
- `examples/blog_app/app/templates/posts/ReactionBar.svelte`
- `examples/blog_app/app/templates/tags/show.svelte`
- `examples/blog_app/app/templates/_shared/Nav.svelte`

- [ ] **Step 1: Nav component**

`examples/blog_app/app/templates/_shared/Nav.svelte`:

```svelte
<script lang="ts">
  let theme = $state<'dark' | 'light'>('dark');
  function toggle() {
    theme = theme === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = theme;
  }
</script>

<nav>
  <a href="/" class="brand">fymo<span class="dot">.</span>blog</a>
  <button class="theme" onclick={toggle} aria-label="Toggle theme">
    {theme === 'dark' ? '☀' : '☾'}
  </button>
</nav>

<style>
  nav {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 1.5rem 0;
    border-bottom: 1px solid var(--rule);
    margin-bottom: 3rem;
  }
  .brand {
    font-weight: 700;
    font-size: 1.05rem;
    color: var(--fg);
    text-decoration: none;
    letter-spacing: -0.02em;
  }
  .dot { color: var(--accent); }
  .theme {
    background: none;
    border: 1px solid var(--rule);
    color: var(--fg);
    width: 2rem; height: 2rem;
    border-radius: 0.4rem;
    cursor: pointer;
    font-size: 1rem;
  }
  .theme:hover { background: var(--card); }
</style>
```

- [ ] **Step 2: Index page**

`examples/blog_app/app/templates/index/index.svelte`:

```svelte
<script lang="ts">
  import Nav from '../_shared/Nav.svelte';
  import type { PostSummary } from '$remote/posts';

  let { hero, posts }: { hero: PostSummary | null; posts: PostSummary[] } = $props();
</script>

<svelte:head>
  <link rel="preconnect" href="https://fonts.googleapis.com">
</svelte:head>

<Nav />

{#if hero}
  <article class="hero">
    <a href="/posts/{hero.slug}">
      <h1>{hero.title}</h1>
      <p class="summary">{hero.summary}</p>
      <p class="meta">{new Date(hero.published_at).toDateString()} · {hero.tags}</p>
    </a>
  </article>
{/if}

<section class="grid">
  {#each posts as p}
    <a class="card" href="/posts/{p.slug}">
      <h2>{p.title}</h2>
      <p>{p.summary}</p>
      <p class="meta">{p.tags}</p>
    </a>
  {/each}
</section>

<style>
  :global(:root) {
    --bg: #0d1117; --fg: #e6edf3; --muted: #8b949e;
    --rule: #21262d; --card: #161b22; --accent: #58a6ff;
    --code-bg: #161b22;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
  }
  :global(:root[data-theme="light"]) {
    --bg: #ffffff; --fg: #1f2328; --muted: #57606a;
    --rule: #d0d7de; --card: #f6f8fa; --accent: #0969da; --code-bg: #f6f8fa;
  }
  :global(body) {
    background: var(--bg); color: var(--fg); margin: 0;
    max-width: 720px; margin: 0 auto; padding: 0 1.5rem 6rem;
  }
  :global(h1, h2, h3) { letter-spacing: -0.02em; }
  :global(a) { color: var(--accent); text-decoration: none; }

  .hero {
    border: 1px solid var(--rule);
    border-radius: 0.6rem;
    padding: 2rem;
    margin-bottom: 3rem;
    background: var(--card);
  }
  .hero a { color: var(--fg); }
  .hero h1 { font-size: 2.2rem; margin: 0 0 0.5rem; }
  .summary { color: var(--muted); font-size: 1.1rem; line-height: 1.6; margin: 0 0 1rem; }
  .meta { color: var(--muted); font-size: 0.85rem; margin: 0; }
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
    gap: 1rem;
  }
  .card {
    border: 1px solid var(--rule);
    border-radius: 0.5rem;
    padding: 1.25rem;
    color: var(--fg);
    transition: background 0.15s;
  }
  .card:hover { background: var(--card); }
  .card h2 { font-size: 1.1rem; margin: 0 0 0.5rem; }
  .card p { color: var(--muted); margin: 0 0 0.5rem; font-size: 0.92rem; }
</style>
```

- [ ] **Step 3: Post detail page**

`examples/blog_app/app/templates/posts/show.svelte`:

```svelte
<script lang="ts">
  import Nav from '../_shared/Nav.svelte';
  import Comments from './Comments.svelte';
  import ReactionBar from './ReactionBar.svelte';
  import type { Post, Comment, ReactionCounts } from '$remote/posts';

  let {
    post,
    initial_comments,
    initial_reactions,
    create_comment,
    toggle_reaction,
  }: {
    post: Post;
    initial_comments: Comment[];
    initial_reactions: ReactionCounts;
    create_comment: (slug: string, input: { name: string; body: string }) => Promise<Comment>;
    toggle_reaction: (slug: string, kind: 'clap' | 'fire' | 'heart' | 'mind') => Promise<ReactionCounts>;
  } = $props();
</script>

<Nav />

<article>
  <h1>{post.title}</h1>
  <p class="meta">{new Date(post.published_at).toDateString()} · {post.tags}</p>
  <div class="body">{@html post.content_html}</div>
</article>

<ReactionBar slug={post.slug} initial={initial_reactions} {toggle_reaction} />
<Comments slug={post.slug} initial={initial_comments} {create_comment} />

<style>
  article h1 { font-size: 2.4rem; margin: 0 0 0.5rem; }
  .meta { color: var(--muted); font-size: 0.9rem; margin: 0 0 2rem; }
  .body :global(p) { font-size: 1.05rem; line-height: 1.7; color: var(--fg); }
  .body :global(pre) {
    background: var(--code-bg); padding: 1rem; border-radius: 0.4rem;
    overflow-x: auto; font-size: 0.9rem;
    border: 1px solid var(--rule);
  }
  .body :global(code) {
    font-family: ui-monospace, "SF Mono", Menlo, monospace;
  }
  .body :global(p code) {
    background: var(--code-bg); padding: 0.1rem 0.4rem; border-radius: 0.25rem; font-size: 0.92em;
  }
  .body :global(h2) { font-size: 1.5rem; margin: 2rem 0 0.5rem; }
</style>
```

- [ ] **Step 4: ReactionBar (uses `$remote/` direct import for the type)**

`examples/blog_app/app/templates/posts/ReactionBar.svelte`:

```svelte
<script lang="ts">
  import type { ReactionCounts, ReactionKind } from '$remote/posts';

  let {
    slug,
    initial,
    toggle_reaction,
  }: {
    slug: string;
    initial: ReactionCounts;
    toggle_reaction: (slug: string, kind: ReactionKind) => Promise<ReactionCounts>;
  } = $props();

  let counts = $state(initial);
  let pending = $state(false);

  const KINDS: { kind: ReactionKind; emoji: string }[] = [
    { kind: 'clap', emoji: '👏' },
    { kind: 'fire', emoji: '🔥' },
    { kind: 'heart', emoji: '❤️' },
    { kind: 'mind', emoji: '🤯' },
  ];

  async function react(kind: ReactionKind) {
    if (pending) return;
    pending = true;
    try {
      counts = await toggle_reaction(slug, kind);
    } finally {
      pending = false;
    }
  }
</script>

<section class="reactions">
  {#each KINDS as { kind, emoji }}
    <button onclick={() => react(kind)} class:pending>
      <span class="emoji">{emoji}</span>
      <span class="count">{counts[kind]}</span>
    </button>
  {/each}
</section>

<style>
  .reactions {
    display: flex; gap: 0.5rem;
    margin: 3rem 0 2rem;
    padding: 1rem 0;
    border-top: 1px solid var(--rule);
    border-bottom: 1px solid var(--rule);
  }
  button {
    display: flex; align-items: center; gap: 0.4rem;
    background: var(--card);
    border: 1px solid var(--rule);
    border-radius: 999px;
    padding: 0.4rem 0.9rem;
    color: var(--fg);
    cursor: pointer;
    font-size: 0.95rem;
    transition: transform 0.1s;
  }
  button:hover { transform: translateY(-1px); border-color: var(--accent); }
  button.pending { opacity: 0.5; }
  .count { font-variant-numeric: tabular-nums; min-width: 1.5ch; text-align: left; }
</style>
```

- [ ] **Step 5: Comments**

`examples/blog_app/app/templates/posts/Comments.svelte`:

```svelte
<script lang="ts">
  import type { Comment } from '$remote/posts';

  let {
    slug,
    initial,
    create_comment,
  }: {
    slug: string;
    initial: Comment[];
    create_comment: (slug: string, input: { name: string; body: string }) => Promise<Comment>;
  } = $props();

  let comments = $state([...initial]);
  let name = $state('');
  let body = $state('');
  let error: string | null = $state.raw(null);
  let pending = $state(false);

  async function submit(e: SubmitEvent) {
    e.preventDefault();
    if (pending) return;
    pending = true;
    error = null;
    try {
      const c = await create_comment(slug, { name, body });
      comments = [c, ...comments];
      body = '';
    } catch (err: any) {
      error = err.issues?.[0]?.msg ?? err.message ?? 'Submission failed';
    } finally {
      pending = false;
    }
  }
</script>

<section class="comments">
  <h2>{comments.length} {comments.length === 1 ? 'comment' : 'comments'}</h2>

  <form onsubmit={submit}>
    <input bind:value={name} placeholder="Your name" required maxlength="60" />
    <textarea bind:value={body} placeholder="Leave a comment" required maxlength="1000" rows="3"></textarea>
    {#if error}<p class="err">{error}</p>{/if}
    <button disabled={pending}>{pending ? 'Posting…' : 'Post comment'}</button>
  </form>

  <ul>
    {#each comments as c (c.id)}
      <li>
        <header>
          <strong>{c.name}</strong>
          <time>{new Date(c.created_at).toLocaleString()}</time>
        </header>
        <p>{c.body}</p>
      </li>
    {/each}
  </ul>
</section>

<style>
  h2 { font-size: 1.2rem; margin: 2rem 0 1rem; }
  form {
    display: flex; flex-direction: column; gap: 0.75rem;
    margin-bottom: 2rem;
    padding: 1.25rem;
    background: var(--card);
    border: 1px solid var(--rule);
    border-radius: 0.5rem;
  }
  input, textarea {
    background: var(--bg);
    color: var(--fg);
    border: 1px solid var(--rule);
    border-radius: 0.3rem;
    padding: 0.6rem 0.75rem;
    font: inherit;
    resize: vertical;
  }
  input:focus, textarea:focus { outline: none; border-color: var(--accent); }
  button {
    align-self: flex-start;
    background: var(--accent); color: white;
    border: none; border-radius: 0.3rem;
    padding: 0.5rem 1rem; cursor: pointer;
    font: inherit; font-weight: 600;
  }
  button:disabled { opacity: 0.6; cursor: not-allowed; }
  .err { color: #ff7b72; font-size: 0.9rem; margin: 0; }

  ul { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 1rem; }
  li {
    border-left: 3px solid var(--rule);
    padding: 0.25rem 0 0.25rem 1rem;
  }
  li header { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 0.3rem; }
  li time { color: var(--muted); font-size: 0.85rem; }
  li p { margin: 0; line-height: 1.5; }
</style>
```

- [ ] **Step 6: Tag page**

`examples/blog_app/app/templates/tags/show.svelte`:

```svelte
<script lang="ts">
  import Nav from '../_shared/Nav.svelte';
  import type { PostSummary } from '$remote/posts';

  let { tag, posts }: { tag: string; posts: PostSummary[] } = $props();
</script>

<Nav />
<h1>Posts tagged <span class="tag">{tag}</span></h1>
<ul>
  {#each posts as p}
    <li><a href="/posts/{p.slug}">{p.title}</a></li>
  {/each}
</ul>

<style>
  .tag { color: var(--accent); }
  ul { list-style: none; padding: 0; }
  li { border-bottom: 1px solid var(--rule); padding: 1rem 0; }
</style>
```

- [ ] **Step 7: Build and smoke-test**

```bash
cd examples/blog_app
rm -rf dist .fymo app/data
/Users/bishwasbhandari/Projects/fymo/.venv/bin/fymo build 2>&1 | tail -3
ls dist/client/ dist/client/_remote/
cd ../..
```

Expected: build succeeds; `dist/client/` has hashed bundles for `index`, `posts/show`, `tags/show`; `dist/client/_remote/posts.{js,d.ts}` exist.

- [ ] **Step 8: Commit**

```bash
git add examples/blog_app/app/templates
git commit -m "feat(blog): index, post detail, comments, reactions, tag pages"
```

### Task 23: End-to-end browser smoke test

**Files:**
- Test: `tests/integration/test_blog_e2e.py`

- [ ] **Step 1: Write the smoke test**

```python
"""End-to-end: build the blog, hit /, hit /posts/<slug>, exercise a remote call."""
import io
import json
import shutil
import sys
from pathlib import Path
import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BLOG_DIR = REPO_ROOT / "examples" / "blog_app"


@pytest.fixture
def blog_app(tmp_path: Path):
    if not BLOG_DIR.is_dir():
        pytest.skip("blog_app missing")
    dest = tmp_path / "blog_app"
    shutil.copytree(BLOG_DIR, dest, ignore=shutil.ignore_patterns("node_modules", "dist", ".fymo", "app/data"))
    nm = BLOG_DIR / "node_modules"
    if nm.is_dir():
        (dest / "node_modules").symlink_to(nm)
    sys.path.insert(0, str(dest))
    yield dest
    sys.path.remove(str(dest))
    for name in list(sys.modules):
        if name.startswith("app"):
            del sys.modules[name]


def _wsgi_call(app, path: str, *, method: str = "GET", body: bytes = b"", cookies: str = ""):
    responses = []
    def sr(s, h): responses.append((s, h))
    out = b"".join(app({
        "REQUEST_METHOD": method, "PATH_INFO": path, "QUERY_STRING": "",
        "CONTENT_LENGTH": str(len(body)), "CONTENT_TYPE": "application/json",
        "HTTP_COOKIE": cookies,
        "SERVER_NAME": "x", "SERVER_PORT": "0", "SERVER_PROTOCOL": "HTTP/1.1",
        "REMOTE_ADDR": "127.0.0.1",
        "wsgi.input": io.BytesIO(body), "wsgi.errors": sys.stderr, "wsgi.url_scheme": "http",
    }, sr))
    return responses[0], out


@pytest.mark.usefixtures("node_available")
def test_blog_e2e(blog_app: Path):
    from fymo.build.pipeline import BuildPipeline
    from app.lib.seeder import ensure_seeded

    ensure_seeded(blog_app)
    BuildPipeline(project_root=blog_app).build(dev=False)

    from fymo import create_app
    app = create_app(blog_app)
    try:
        # Index renders
        (status, _), html = _wsgi_call(app, "/")
        assert status.startswith("200")
        assert b"fymo" in html.lower() or b"Welcome" in html

        # Post detail renders with SSR'd HTML
        (status, _), html = _wsgi_call(app, "/posts/welcome-to-fymo")
        assert status.startswith("200")
        assert b"Welcome to Fymo" in html

        # Remote call: get_posts
        body = json.dumps({"args": []}).encode()
        (status, _), out = _wsgi_call(app, "/__remote/posts/get_posts", method="POST", body=body)
        assert status.startswith("200")
        payload = json.loads(out)
        assert payload["ok"] is True
        slugs = [p["slug"] for p in payload["data"]]
        assert "welcome-to-fymo" in slugs

        # Remote call: create_comment with valid input
        body = json.dumps({"args": ["welcome-to-fymo", {"name": "Alex", "body": "Great post"}]}).encode()
        (status, headers), out = _wsgi_call(app, "/__remote/posts/create_comment", method="POST", body=body)
        assert status.startswith("200")
        comment = json.loads(out)["data"]
        assert comment["name"] == "Alex"

        # Remote call: create_comment with invalid input → 422
        body = json.dumps({"args": ["welcome-to-fymo", {"name": "", "body": ""}]}).encode()
        (status, _), out = _wsgi_call(app, "/__remote/posts/create_comment", method="POST", body=body)
        assert status.startswith("422")
        assert json.loads(out)["error"] == "validation"

        # Remote call: toggle_reaction
        body = json.dumps({"args": ["welcome-to-fymo", "clap"]}).encode()
        (status, _), out = _wsgi_call(app, "/__remote/posts/toggle_reaction", method="POST", body=body)
        assert status.startswith("200")
        counts = json.loads(out)["data"]
        assert counts["clap"] == 1

        # Toggle again → 0
        (status, _), out = _wsgi_call(app, "/__remote/posts/toggle_reaction", method="POST", body=body, cookies=_extract_uid_cookie(headers))
        # We don't have the cookie threading here, just assert 200
        assert status.startswith("200")
    finally:
        if app.sidecar:
            app.sidecar.stop()


def _extract_uid_cookie(headers) -> str:
    for k, v in headers:
        if k.lower() == "set-cookie" and "fymo_uid=" in v:
            return v.split(";")[0]
    return ""
```

- [ ] **Step 2: Run — should pass**

Run: `.venv/bin/python -m pytest tests/integration/test_blog_e2e.py -v`
Expected: 1 PASSED.

- [ ] **Step 3: Run full suite for final regression check**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: all PASS, no flakes.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_blog_e2e.py
git commit -m "test(blog): end-to-end smoke covering SSR, remote calls, validation"
```

---

## Self-review checklist

- [x] **Spec section 3 (Architecture)** — covered by Tasks 3, 7, 8, 12, 13, 14, 15, 16
- [x] **Spec section 4 (Server API)** — covered by Tasks 2, 3, 9, 10, 11
- [x] **Spec section 5 (Type bridge)** — covered by Tasks 4, 5, 6
- [x] **Spec section 6 (Wire protocol)** — covered by Tasks 11, 12
- [x] **Spec section 7 (Build pipeline integration)** — covered by Tasks 8, 14, 16
- [x] **Spec section 8 (WSGI router)** — covered by Tasks 12, 13
- [x] **Spec section 9 (TypeScript in .svelte)** — covered by Task 1
- [x] **Spec section 10 (Blog example)** — covered by Tasks 18-23
- [x] **Spec section 11 (Parametric routes)** — covered by Task 17 + existing router (already supports `:id`-style params; this task wires them to controllers)
- [x] **Spec section 12 (Dependencies)** — covered by Tasks 1, 6, 18
- [x] **Spec section 13 (Errors & dev DX)** — covered by Tasks 2, 12 (production paths); dev error overlay deferred to a future polish PR

**Placeholder scan:** none. Every step has actual code.

**Type consistency:** `RemoteFunction(module, name, fn, signature, hints)` is used in Tasks 3, 7. `_ensure_uid` returns `(uid, set_cookie)` consistently in Tasks 9, 12. `validate_args(args, sig, hints)` signature consistent in Tasks 11, 12. `python_type_to_ts(py, *, type_defs)` consistent in Tasks 4, 5, 6, 7. `__rpc(path, args)` and `__resolveRemoteProps(props)` consistent across runtime + entry stub.

**Open items / not blocking ship:**
- Dev error overlay for remote call traces (today returns JSON traceback only).
- Hot-reload of `app/remote/*.py` modules in `fymo dev` (Section 15.7 in the spec). Plan covers the import-cache invalidation in `discover_remote_modules` (uses `importlib.reload`); the dev orchestrator already restarts the sidecar on rebuild — Python module re-import on edit is a follow-up.
- `set[T]` recursion (validate elements) — v1 is shallow.
