import path from 'node:path';

/**
 * Resolves `$remote/<name>` imports to dist/client/_remote/<name>.js.
 * The codegen step (Python side) must have run first.
 *
 * @param {{ remoteDir: string }} options - absolute path to dist/client/_remote/
 */
export function fymoRemotePlugin({ remoteDir }) {
    return {
        name: 'fymo-remote',
        setup(build) {
            build.onResolve({ filter: /^\$remote\// }, (args) => {
                const name = args.path.slice('$remote/'.length);
                const filePath = path.join(remoteDir, `${name}.js`);
                return { path: filePath };
            });
        },
    };
}
