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
import { build } from 'esbuild';
import sveltePlugin from 'esbuild-svelte';
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const config = JSON.parse(process.argv[2]);

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
        plugins: [sveltePlugin({
            compilerOptions: { generate: 'server', dev: false },
        })],
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
    await copySidecar();
    process.stdout.write(JSON.stringify({ ok: true, server: server.metafile }));
} catch (err) {
    process.stdout.write(JSON.stringify({
        ok: false,
        error: err.message || String(err),
        stack: err.stack || '',
    }));
    process.exit(1);
}
