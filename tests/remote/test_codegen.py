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
    return RemoteFunction(module=module_name, name=fn.__name__, fn=fn, signature=sig, hints=hints, module_hash="0" * 12)


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
    assert "'get_post'" in js

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
    assert "/_fymo/remote/" in runtime


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
