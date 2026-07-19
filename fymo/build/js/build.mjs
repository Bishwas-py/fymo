#!/usr/bin/env node
/**
 * Fymo build — invoked by Python orchestrator.
 *
 * Reads a JSON config from argv[2]:
 *   { projectRoot, distDir, routes: [{name, entryPath}], clientEntries: {name: path}, dev }
 *
 * Writes:
 *   <distDir>/ssr/<route>.mjs              (server pass)
 *   <distDir>/sidecar.mjs                  (copied)
 * Prints:
 *   { ok: true, server: { ... metafile ... } } on stdout
 */
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { createRequire } from 'node:module';
import { fymoRemotePlugin } from './plugins/remote.mjs';
import { fymoBroadcastPlugin } from './plugins/broadcast.mjs';
import { fymoRoutePlugin } from './plugins/router.mjs';
import { authPlugin } from './plugins/auth.mjs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const config = JSON.parse(process.argv[2]);
const routeRuntimePath = path.join(__dirname, 'runtime', 'route.js');
const authFile = path.join(config.distDir, 'client', '_auth.js');

// Resolve esbuild, esbuild-svelte, and svelte-preprocess from the project's
// own node_modules, not fymo's. A bare `import ... from 'esbuild'` resolves
// against this file's own location, which once fymo is a real pip install
// (site-packages/fymo/build/js/) never has a node_modules in its ancestry at
// all. esbuild-svelte and svelte-preprocess already need this treatment so
// the Svelte version used for compilation matches the one used at SSR
// runtime; esbuild needs it for the same underlying reason, resolvability
// from the target project rather than from fymo's own package tree.
const projectRequire = createRequire(path.join(config.projectRoot, 'package.json'));
const { build } = await import(pathToFileURL(projectRequire.resolve('esbuild')).href);
const sveltePlugin = (await import(pathToFileURL(projectRequire.resolve('esbuild-svelte')).href)).default;
const sveltePreprocess = (await import(pathToFileURL(projectRequire.resolve('svelte-preprocess')).href)).default;

async function buildServer() {
    const entryPoints = Object.fromEntries(
        config.routes.map(r => [r.name, r.entryPath])
    );
    return await build({
        entryPoints,
        outdir: path.join(config.distDir, 'ssr'),
        outExtension: { '.js': '.mjs' },
        format: 'esm',
        platform: 'node',
        bundle: true,
        splitting: false,
        minify: !config.dev,
        sourcemap: config.dev ? 'linked' : false,
        metafile: true,
        external: ['$remote/*', '$broadcast/*'],
        // Layouts import their stylesheets (app/assets/*.css); the client
        // pass bundles those into the entry's sibling CSS output, but the
        // node SSR bundle has no use for CSS -- empty-load it so the import
        // is a no-op instead of a build error or a runtime crash.
        loader: { '.css': 'empty' },
        // fymoRoutePlugin resolves `$route` to fymo's own shipped
        // runtime/route.js, which lives inside fymo's install location, not
        // the project. Its own `import ... from 'svelte/store'` would
        // otherwise be resolved against route.js's directory ancestry (same
        // problem the createRequire calls above solve for esbuild itself),
        // which is empty for a real pip install. nodePaths is esbuild's
        // NODE_PATH-style fallback search list, tried once normal ancestor
        // resolution comes up empty.
        nodePaths: [path.join(config.projectRoot, 'node_modules')],
        plugins: [
            fymoRoutePlugin({ runtimePath: routeRuntimePath }),
            // Bundled (never external, unlike $remote): the identity store
            // must exist inside each SSR module so `$identity` renders
            // server-side from the sidecar's per-render global.
            authPlugin({ authFile }),
            sveltePlugin({
                preprocess: sveltePreprocess(),
                compilerOptions: { generate: 'server', dev: false, css: 'external' },
            }),
        ],
        logLevel: 'silent',
    });
}

async function buildClient() {
    const entryPoints = Object.fromEntries(
        Object.entries(config.clientEntries).map(([name, p]) => [name, p])
    );
    return await build({
        entryPoints,
        outdir: path.join(config.distDir, 'client'),
        format: 'esm',
        platform: 'browser',
        bundle: true,
        splitting: true,
        entryNames: '[name].[hash]',
        chunkNames: 'chunk-[name].[hash]',
        assetNames: '[name].[hash]',
        minify: !config.dev,
        sourcemap: config.dev ? 'linked' : false,
        metafile: true,
        // Binary assets referenced from bundled CSS (fonts via @font-face,
        // images via url()) go through the file loader: content-hashed into
        // dist/client/ per assetNames above, with the css url() rewritten to
        // publicPath + the hashed filename. publicPath must be the URL the
        // outdir is actually served under, or the rewritten urls 404.
        loader: {
            '.woff2': 'file', '.woff': 'file', '.ttf': 'file', '.otf': 'file',
            '.png': 'file', '.jpg': 'file', '.jpeg': 'file', '.gif': 'file',
            '.webp': 'file', '.svg': 'file', '.avif': 'file', '.ico': 'file',
        },
        publicPath: '/dist/client',
        // Root-absolute /static/ urls are verbatim references to app/static
        // (served unhashed at /static/), not build inputs -- left untouched.
        external: ['/static/*'],
        // See buildServer()'s nodePaths comment -- the client bundle also
        // imports `$route` -> route.js, with the same svelte/store fallback
        // requirement.
        nodePaths: [path.join(config.projectRoot, 'node_modules')],
        plugins: [
            fymoRemotePlugin({ remoteDir: path.join(config.distDir, 'client', '_remote') }),
            fymoBroadcastPlugin({ broadcastDir: path.join(config.distDir, 'client', '_broadcast') }),
            fymoRoutePlugin({ runtimePath: routeRuntimePath }),
            authPlugin({ authFile }),
            sveltePlugin({
                preprocess: sveltePreprocess(),
                compilerOptions: { generate: 'client', dev: false, css: 'external', discloseVersion: false },
            }),
        ],
        logLevel: 'silent',
    });
}

async function copySidecar() {
    const src = path.join(__dirname, 'sidecar.mjs');
    const dst = path.join(config.distDir, 'sidecar.mjs');
    await fs.mkdir(path.dirname(dst), { recursive: true });
    await fs.copyFile(src, dst);
}

try {
    await fs.mkdir(config.distDir, { recursive: true });
    const server = await buildServer();
    const client = await buildClient();
    await copySidecar();
    process.stdout.write(JSON.stringify({ ok: true, server: server.metafile, client: client.metafile }));
} catch (err) {
    process.stdout.write(JSON.stringify({
        ok: false,
        error: err.message || String(err),
        stack: err.stack || '',
    }));
    process.exit(1);
}
