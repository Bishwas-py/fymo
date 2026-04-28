#!/usr/bin/env node
import * as esbuild from 'esbuild';
import sveltePlugin from 'esbuild-svelte';
import fs from 'node:fs/promises';
import path from 'node:path';

const config = JSON.parse(process.argv[2]);

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
        plugins: [
            sveltePlugin({ compilerOptions: { generate: 'server', dev: false } }),
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
        plugins: [
            sveltePlugin({ compilerOptions: { generate: 'client', dev: false } }),
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
