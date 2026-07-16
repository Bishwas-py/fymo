/**
 * Resolves the `$route` specifier to fymo's own shipped
 * runtime/route.svelte.js -- a fixed file, not a per-project generated one,
 * since its content never varies by app.
 *
 * @param {{ runtimePath: string }} options - absolute path to route.svelte.js
 */
export function fymoRoutePlugin({ runtimePath }) {
    return {
        name: 'fymo-route',
        setup(build) {
            build.onResolve({ filter: /^\$route$/ }, () => ({ path: runtimePath }));
        },
    };
}
