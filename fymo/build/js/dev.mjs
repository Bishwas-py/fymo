#!/usr/bin/env node
import fs from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { createRequire } from 'node:module';
import { fymoRemotePlugin } from './plugins/remote.mjs';
import { fymoBroadcastPlugin } from './plugins/broadcast.mjs';
import { fymoRoutePlugin } from './plugins/router.mjs';
import { fymoAuthPlugin } from './plugins/fymo_auth.mjs';

const config = JSON.parse(process.argv[2]);
const routeRuntimePath = path.join(path.dirname(new URL(import.meta.url).pathname), 'runtime', 'route.js');
const fymoAuthDir = path.join(config.distDir, 'client', '_fymo');

// Resolve esbuild, esbuild-svelte, and svelte-preprocess from the project's
// own node_modules so the Svelte version used to COMPILE components matches
// the one esbuild bundles for the SSR runtime, and so esbuild itself is even
// resolvable at all once fymo is a real pip install with no node_modules of
// its own. Bare imports here would resolve from fymo's own package tree
// instead (or, for esbuild-svelte/svelte-preprocess, from whatever version
// happens to sit there, causing a Svelte version skew where the compiler
// emits lifecycle calls the runtime no longer exports, the bundle then
// calls `(void 0)()` and every render throws). Mirrors build.mjs.
const projectRequire = createRequire(path.join(config.projectRoot, 'package.json'));
const esbuild = await import(pathToFileURL(projectRequire.resolve('esbuild')).href);
const sveltePlugin = (await import(pathToFileURL(projectRequire.resolve('esbuild-svelte')).href)).default;
const sveltePreprocess = (await import(pathToFileURL(projectRequire.resolve('svelte-preprocess')).href)).default;

function emit(event) {
    process.stdout.write(JSON.stringify(event) + "\n");
}

async function makeServerCtx() {
    const entryPoints = Object.fromEntries(config.routes.map(r => [r.name, r.entryPath]));
    return await esbuild.context({
        entryPoints,
        outdir: path.join(config.distDir, 'ssr'),
        outExtension: { '.js': '.mjs' },
        format: 'esm',
        platform: 'node',
        bundle: true,
        splitting: false,
        minify: false,
        sourcemap: 'linked',
        metafile: true,
        external: ['$remote/*', '$broadcast/*'],
        // Layout-imported stylesheets are a client concern; the node SSR
        // bundle empty-loads them so the import is a no-op. Mirrors build.mjs.
        loader: { '.css': 'empty' },
        // fymoRoutePlugin resolves `$route` to fymo's own shipped
        // runtime/route.js, which lives inside fymo's install location, not
        // the project. Its own `import ... from 'svelte/store'` would
        // otherwise be resolved against route.js's directory ancestry (same
        // problem the createRequire calls above solve for esbuild itself),
        // which is empty for a real pip install. nodePaths is esbuild's
        // NODE_PATH-style fallback search list, tried once normal ancestor
        // resolution comes up empty. Mirrors build.mjs.
        nodePaths: [path.join(config.projectRoot, 'node_modules')],
        plugins: [
            fymoRoutePlugin({ runtimePath: routeRuntimePath }),
            // Bundled for SSR (never external), mirroring build.mjs.
            fymoAuthPlugin({ fymoDir: fymoAuthDir }),
            sveltePlugin({ preprocess: sveltePreprocess(), compilerOptions: { generate: 'server', dev: false } }),
            { name: 'fymo-emit', setup(build) { build.onEnd(r => emit({ type: 'server-rebuild', errors: r.errors.map(e => e.text) })); } },
        ],
        logLevel: 'silent',
    });
}

async function makeClientCtx() {
    const entryPoints = Object.fromEntries(Object.entries(config.clientEntries));
    return await esbuild.context({
        entryPoints,
        outdir: path.join(config.distDir, 'client'),
        format: 'esm',
        platform: 'browser',
        bundle: true,
        splitting: true,
        entryNames: '[name].[hash]',
        chunkNames: 'chunk-[name].[hash]',
        assetNames: '[name].[hash]',
        minify: false,
        sourcemap: 'linked',
        metafile: true,
        // Binary assets referenced from bundled CSS are content-hashed into
        // dist/client/ and their url()s rewritten under publicPath;
        // root-absolute /static/ urls are verbatim static references and
        // stay external. Mirrors build.mjs.
        loader: {
            '.woff2': 'file', '.woff': 'file', '.ttf': 'file', '.otf': 'file',
            '.png': 'file', '.jpg': 'file', '.jpeg': 'file', '.gif': 'file',
            '.webp': 'file', '.svg': 'file', '.avif': 'file', '.ico': 'file',
        },
        publicPath: '/dist/client',
        external: ['/static/*'],
        // See makeServerCtx()'s nodePaths comment -- the client bundle also
        // imports `$route` -> route.js, with the same svelte/store fallback
        // requirement.
        nodePaths: [path.join(config.projectRoot, 'node_modules')],
        plugins: [
            fymoRemotePlugin({ remoteDir: path.join(config.distDir, 'client', '_remote') }),
            fymoBroadcastPlugin({ broadcastDir: path.join(config.distDir, 'client', '_broadcast') }),
            fymoRoutePlugin({ runtimePath: routeRuntimePath }),
            fymoAuthPlugin({ fymoDir: fymoAuthDir }),
            sveltePlugin({ preprocess: sveltePreprocess(), compilerOptions: { generate: 'client', dev: false } }),
            { name: 'fymo-emit', setup(build) { build.onEnd(r => emit({ type: 'client-rebuild', errors: r.errors.map(e => e.text), metafile: r.metafile })); } },
        ],
        logLevel: 'silent',
    });
}

async function copySidecar() {
    const __dirname = path.dirname(new URL(import.meta.url).pathname);
    await fs.mkdir(config.distDir, { recursive: true });
    await fs.copyFile(path.join(__dirname, 'sidecar.mjs'), path.join(config.distDir, 'sidecar.mjs'));
}

await copySidecar();
const serverCtx = await makeServerCtx();
const clientCtx = await makeClientCtx();
await Promise.all([serverCtx.watch(), clientCtx.watch()]);
emit({ type: 'ready' });
