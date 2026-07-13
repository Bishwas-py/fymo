import path from 'node:path';

/**
 * Resolves `$broadcast/<name>` imports to dist/client/_broadcast/<name>.js.
 * The codegen step (Python side) must have run first — mirrors remote.mjs.
 *
 * @param {{ broadcastDir: string }} options - absolute path to dist/client/_broadcast/
 */
export function fymoBroadcastPlugin({ broadcastDir }) {
    return {
        name: 'fymo-broadcast',
        setup(build) {
            build.onResolve({ filter: /^\$broadcast\// }, (args) => {
                const name = args.path.slice('$broadcast/'.length);
                const filePath = path.join(broadcastDir, `${name}.js`);
                return { path: filePath };
            });
        },
    };
}
