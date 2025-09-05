#!/usr/bin/env node

import { build } from 'esbuild';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

async function bundleSvelteRuntime() {
    console.log('Building production Svelte runtime...');
    
    // Ensure dist directory exists
    const distDir = path.join(__dirname, 'dist');
    if (!fs.existsSync(distDir)) {
        fs.mkdirSync(distDir, { recursive: true });
    }

    try {
        // Bundle the actual Svelte 5 internal client runtime
        const result = await build({
            stdin: {
                contents: `
                    // Export everything from Svelte's internal client runtime
                    export * from 'svelte/internal/client';
                    
                    // Also export mount and hydrate from main svelte package
                    export { mount, hydrate } from 'svelte';
                    
                    console.log('✅ Svelte 5 runtime loaded');
                `,
                loader: 'js',
                resolveDir: __dirname
            },
            bundle: true,
            format: 'esm',
            outfile: path.join(distDir, 'svelte-runtime.js'),
            platform: 'browser',
            target: 'es2020',
            minify: false, // Keep readable for debugging in development
            sourcemap: 'inline',
            metafile: true,
            define: {
                'import.meta.env.DEV': 'false',
                'import.meta.env.PROD': 'true'
            }
        });

        console.log('✅ Svelte runtime bundled successfully');
        
        // Get bundle size
        const stats = fs.statSync(path.join(distDir, 'svelte-runtime.js'));
        console.log(`Bundle size: ${(stats.size / 1024).toFixed(2)} KB`);
        
        // Write metadata for Python to use
        const metadata = {
            runtime_path: path.join(distDir, 'svelte-runtime.js'),
            bundle_size: stats.size,
            build_time: new Date().toISOString()
        };
        
        fs.writeFileSync(
            path.join(distDir, 'runtime-metadata.json'), 
            JSON.stringify(metadata, null, 2)
        );
        
        console.log('📦 Runtime metadata saved to dist/runtime-metadata.json');
        
    } catch (error) {
        console.error('Failed to bundle Svelte runtime:', error);
        process.exit(1);
    }
}

// Run the bundler
bundleSvelteRuntime();
