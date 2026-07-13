import path from 'node:path';

/**
 * Fails the CLIENT build if any file under app/lib/server/** is reached by
 * the client bundle graph. Mirrors SvelteKit's $lib/server boundary: code
 * meant to stay server-only (secrets, DB helpers, etc.) must never ship to
 * the browser, and this should be a hard build failure, not a lint warning.
 *
 * Deliberately NOT registered in buildServer() -- server-only code is
 * exactly what should keep working fine there.
 *
 * The `filter` regex is applied natively by esbuild before any JS callback
 * runs, so this costs nothing for the thousands of unrelated files (svelte
 * internals, node_modules, etc.) in a typical build -- the callback only
 * ever fires for paths that already look like app/lib/server/**. If no such
 * directory exists in a project, this plugin is a complete no-op.
 *
 * @param {{ projectRoot: string }} options
 */
export function fymoServerOnlyGuardPlugin({ projectRoot }) {
    const serverOnlyDir = path.join(projectRoot, 'app', 'lib', 'server') + path.sep;
    const filter = /[/\\]app[/\\]lib[/\\]server[/\\]/;
    return {
        name: 'fymo-server-only-guard',
        setup(build) {
            build.onLoad({ filter }, (args) => {
                // The regex is a cheap pre-filter; this prefix check against
                // the resolved absolute path is the authoritative test (guards
                // against e.g. node_modules/some-lib/server/foo.js coincidentally
                // matching the regex without actually being under the project's
                // app/lib/server/ directory).
                if (!args.path.startsWith(serverOnlyDir)) return null;
                const rel = path.relative(projectRoot, args.path);
                return {
                    errors: [{
                        text:
                            `"${rel}" is under app/lib/server/ (server-only) but was ` +
                            `reached from the client bundle. Move client-safe code out ` +
                            `of app/lib/server/, or stop importing it from client-reachable ` +
                            `components.`,
                    }],
                };
            });
        },
    };
}
