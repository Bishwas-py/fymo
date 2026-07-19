/**
 * Resolves the `$auth` specifier to dist/client/_auth.js, the generated
 * identity store. The codegen step (fymo/auth/codegen.py, run by
 * prepare_build_config) must have emitted the module first (mirrors
 * remote.mjs/broadcast.mjs).
 *
 * Registered in BOTH the server and client passes, unlike $remote: the
 * $auth identity store must be bundled into the SSR modules so a
 * template's `$identity` reads render server-side too.
 *
 * The retired `$fymo/` prefix resolves to nothing, on purpose, with an
 * error that names the rename: a stale import should teach its own fix
 * instead of dying as a generic could-not-resolve (issue #86).
 *
 * @param {{ authFile: string }} options - absolute path to dist/client/_auth.js
 */
export function authPlugin({ authFile }) {
    return {
        name: 'fymo-auth',
        setup(build) {
            build.onResolve({ filter: /^\$auth$/ }, () => ({ path: authFile }));
            build.onResolve({ filter: /^\$fymo\// }, (args) => ({
                errors: [{ text: `$fymo/auth was renamed to $auth, update the import (found '${args.path}')` }],
            }));
        },
    };
}
