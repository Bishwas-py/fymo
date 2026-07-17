import path from 'node:path';

/**
 * Resolves `$fymo/<name>` imports to dist/client/_fymo/<name>.js.
 * The codegen step (fymo/auth/codegen.py, run by prepare_build_config)
 * must have emitted the module first (mirrors remote.mjs/broadcast.mjs).
 *
 * Registered in BOTH the server and client passes, unlike $remote: the
 * $fymo/auth identity store must be bundled into the SSR modules so a
 * template's `$identity` reads render server-side too.
 *
 * @param {{ fymoDir: string }} options - absolute path to dist/client/_fymo/
 */
export function fymoAuthPlugin({ fymoDir }) {
    return {
        name: 'fymo-auth',
        setup(build) {
            build.onResolve({ filter: /^\$fymo\// }, (args) => {
                const name = args.path.slice('$fymo/'.length);
                const filePath = path.join(fymoDir, `${name}.js`);
                return { path: filePath };
            });
        },
    };
}
