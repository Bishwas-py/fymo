// fymo's reactive current-route state, resolved as `$route` by
// fymo/build/js/plugins/router.mjs. One shared chunk across every route
// entry (fymo build's client bundle splits on a single multi-entry build()),
// so mutating these properties -- never reassigning `route` itself -- stays
// reactive across a soft nav between two different routes' bundles.
// Seeded and updated by the boot code in fymo/build/entry_generator.py, not
// by the SSR render pass, so reads inside `$effect`/event handlers are
// correct from first paint on; a top-level template read during the very
// first render may briefly differ from what the server rendered.
export const route = $state({ pathname: '', search: '', params: {} });
