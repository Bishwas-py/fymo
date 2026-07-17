"""$fymo/auth client module emission (issue #80 phase 4).

Mirrors the $remote/$broadcast codegen conventions: a .js module plus a
.d.ts under dist/client/_fymo/, dependency-free apart from svelte/store
(which every fymo app already bundles for $route)."""
from pathlib import Path

from fymo.auth.codegen import emit_identity_client


def test_emits_js_and_dts(tmp_path: Path):
    emit_identity_client(tmp_path)
    js = (tmp_path / "client" / "_fymo" / "auth.js").read_text()
    dts = (tmp_path / "client" / "_fymo" / "auth.d.ts").read_text()
    assert "AUTO-GENERATED" in js
    assert "export const identity" in js
    assert "export function __setIdentity" in js
    assert "from 'svelte/store'" in js
    assert "export declare const identity" in dts


def test_ssr_side_reads_the_per_render_global(tmp_path: Path):
    """During SSR the store's value is the identity the sidecar installed
    for the current render (globalThis.__fymoIdentity), read lazily per
    subscription so one bundled copy per route module stays correct
    across renders with different identities."""
    emit_identity_client(tmp_path)
    js = (tmp_path / "client" / "_fymo" / "auth.js").read_text()
    assert "globalThis.__fymoIdentity" in js
    assert "typeof window" in js


def test_store_follows_svelte_store_contract(tmp_path: Path):
    emit_identity_client(tmp_path)
    js = (tmp_path / "client" / "_fymo" / "auth.js").read_text()
    assert "subscribe" in js
