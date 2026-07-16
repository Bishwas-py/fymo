// fymo's reactive current-route state, resolved as `$route` by
// fymo/build/js/plugins/router.mjs. A plain `svelte/store` writable, not a
// `.svelte.js` $state module: esbuild bundled a $state-backed version as two
// separate, disconnected copies of Svelte's client runtime (compileModule()
// vs the regular component compiler emit different runtime import paths),
// so a mutation on one side was invisible to effects reading it on the
// other. `writable` isn't compiler-transformed at its definition site --
// only the `$route` auto-subscription sugar inside a consuming .svelte file
// is, and that's the same, already-proven-shared code path app/lib/auth.ts's
// `user`/`ready` stores already go through in this exact build.
//
// Seeded and updated by the boot code in fymo/build/entry_generator.py, not
// by the SSR render pass, so `$route` reads inside `$effect`/event handlers
// are correct from first paint on; a top-level template read during the
// very first render may briefly differ from what the server rendered.
import { writable } from 'svelte/store';

export const route = writable({ pathname: '', search: '', params: {} });

// Seeds route from this request's own URL + the server's resolved
// :id-style params (the svelte-route-params island) -- call once, before
// hydrate()/mount(), so the first subscriber sees the real value.
export function seedRoute() {
    const el = document.getElementById('svelte-route-params');
    route.set({
        pathname: window.location.pathname,
        search: window.location.search,
        params: el ? JSON.parse(el.textContent) : {},
    });
}

// Applies a soft nav's outcome: the URL just navigated to, plus the
// server's resolved params for it (soft_nav.py's `params` envelope field).
export function applyRouteNav(path, params) {
    const url = new URL(path, window.location.origin);
    route.set({ pathname: url.pathname, search: url.search, params: params || {} });
}
