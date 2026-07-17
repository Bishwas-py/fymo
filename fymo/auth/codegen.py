"""Generate the $fymo/auth client module, the identity store the Svelte
layer reads (issue #80 phase 4).

Mirrors the $remote/$broadcast codegen conventions: a .js module plus a
.d.ts emitted under dist/client/_fymo/, resolved by the fymo-auth esbuild
plugin (fymo/build/js/plugins/fymo_auth.mjs) in both the server and client
passes. Unlike those two the content is fixed, not derived from app code:
what varies per app is the projection output flowing through the store at
runtime, never the module itself.

The store's value is the public_identity projection output (or null when
anonymous), delivered three ways:
  * SSR: the sidecar installs it as globalThis.__fymoIdentity per render;
    the server-side store reads that lazily per subscription, so each
    route bundle's own copy stays correct across renders.
  * Boot: the generated client entry seeds the writable from the
    fymo-identity JSON island before hydrate().
  * Soft nav: every data envelope carries an `identity` field the entry
    pushes into the store.
"""
from __future__ import annotations

from pathlib import Path

_AUTH_JS = '''// AUTO-GENERATED. Do not edit. Fymo identity store ($fymo/auth).
import { writable } from 'svelte/store';

const _identity = writable(null);

// Svelte-store contract. On the server every subscription reads the
// identity the sidecar installed for the current render; in the browser
// it is a plain readable view of the boot/soft-nav-fed writable.
export const identity = typeof window === 'undefined'
    ? {
        subscribe(run) {
            run(globalThis.__fymoIdentity === undefined ? null : globalThis.__fymoIdentity);
            return () => {};
        },
    }
    : { subscribe: _identity.subscribe };

// Internal: called by fymo's generated boot/soft-nav code. App code reads
// the `identity` store; it never writes it (the server owns the value).
export function __setIdentity(value) {
    _identity.set(value === undefined ? null : value);
}
'''

_AUTH_DTS = '''// AUTO-GENERATED. Do not edit. Fymo identity store ($fymo/auth).
import type { Readable } from 'svelte/store';

/** The public_identity projection output; shape is app-defined.
 * The default projection is { uid: string }. */
export type PublicIdentity = Record<string, unknown>;

/** The signed-in identity as projected for the client, or null when
 * anonymous. Hydrated from SSR, updated on every soft navigation. */
export declare const identity: Readable<PublicIdentity | null>;

/** Internal: fymo's generated boot code feeds the store. Not app API. */
export declare function __setIdentity(value: PublicIdentity | null): void;
'''


def emit_identity_client(dist_dir: Path) -> None:
    """Write dist/client/_fymo/auth.{js,d.ts}. Always emitted: every
    generated client entry imports $fymo/auth, identity chain or not."""
    out = dist_dir / "client" / "_fymo"
    out.mkdir(parents=True, exist_ok=True)
    (out / "auth.js").write_text(_AUTH_JS)
    (out / "auth.d.ts").write_text(_AUTH_DTS)
