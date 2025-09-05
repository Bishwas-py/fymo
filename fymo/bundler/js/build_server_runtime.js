#!/usr/bin/env node

import { build } from 'esbuild';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

async function bundleSvelteServerRuntime() {
    console.log('Building Svelte server runtime for SSR...');
    
    // Ensure dist directory exists
    const distDir = path.join(__dirname, 'dist');
    if (!fs.existsSync(distDir)) {
        fs.mkdirSync(distDir, { recursive: true });
    }

    try {
        // Bundle the actual Svelte 5 internal server runtime
        const result = await build({
            stdin: {
                contents: `
                    // Export everything from Svelte's internal server runtime
                    // This includes all SSR-specific functions
                    import * as server from 'svelte/internal/server';
                    
                    // Create a global object that can be accessed from STPyV8
                    const SvelteServer = {
                        ...server,
                        // Ensure key functions are exposed (verified from actual exports)
                        FILENAME: server.FILENAME,
                        HMR: server.HMR,
                        attr: server.attr,
                        attr_class: server.attr_class,
                        attr_style: server.attr_style,
                        bind_props: server.bind_props,
                        element: server.element,
                        push_element: server.push_element,
                        pop_element: server.pop_element,
                        ensure_array_like: server.ensure_array_like,
                        escape: server.escape,
                        head: server.head,
                        html: server.html,
                        push: server.push,
                        pop: server.pop,
                        render: server.render,
                        slot: server.slot,
                        spread_attributes: server.spread_attributes,
                        spread_props: server.spread_props,
                        stringify: server.stringify,
                        to_array: server.to_array,
                        
                        // Store utilities
                        store_get: server.store_get,
                        store_set: server.store_set,
                        store_mutate: server.store_mutate,
                        update_store: server.update_store,
                        update_store_pre: server.update_store_pre,
                        unsubscribe_stores: server.unsubscribe_stores,
                        
                        // Other utilities
                        assign_payload: server.assign_payload,
                        copy_payload: server.copy_payload,
                        css_props: server.css_props,
                        derived: server.derived,
                        fallback: server.fallback,
                        inspect: server.inspect,
                        on_destroy: server.on_destroy,
                        once: server.once,
                        props_id: server.props_id,
                        rest_props: server.rest_props,
                        sanitize_props: server.sanitize_props,
                        sanitize_slots: server.sanitize_slots,
                        snapshot: server.snapshot,
                        
                        // Validation functions
                        validate_dynamic_element_tag: server.validate_dynamic_element_tag,
                        validate_snippet_args: server.validate_snippet_args,
                        validate_void_dynamic_element: server.validate_void_dynamic_element,
                        
                        // Helper to create render context
                        createRenderContext: () => {
                            return {
                                out: '',
                                anchor: 0,
                                flags: 0
                            };
                        }
                    };
                    
                    // Export for module systems
                    if (typeof module !== 'undefined' && module.exports) {
                        module.exports = SvelteServer;
                    }
                    
                    // Also make it globally available for STPyV8
                    if (typeof globalThis !== 'undefined') {
                        globalThis.SvelteServer = SvelteServer;
                        globalThis.$ = SvelteServer; // Also expose as $ for compatibility
                    }
                    
                    console.log('✅ Svelte server runtime loaded');
                `,
                loader: 'js',
                resolveDir: __dirname
            },
            bundle: true,
            format: 'cjs',  // Use CommonJS for STPyV8 compatibility
            // No globalName needed for CommonJS
            outfile: path.join(distDir, 'svelte-server-runtime.js'),
            platform: 'neutral',  // Works in both Node and V8
            target: 'es2020',
            minify: false,
            sourcemap: false,  // No sourcemap for server runtime
            metafile: true,
            define: {
                'import.meta.env.DEV': 'false',
                'import.meta.env.PROD': 'true',
                'process.env.NODE_ENV': '"production"'
            }
        });

        console.log('✅ Svelte server runtime bundled successfully');
        
        // Get bundle size
        const stats = fs.statSync(path.join(distDir, 'svelte-server-runtime.js'));
        console.log(`Server runtime size: ${(stats.size / 1024).toFixed(2)} KB`);
        
        // Update metadata
        const metadataPath = path.join(distDir, 'runtime-metadata.json');
        let metadata = {};
        
        if (fs.existsSync(metadataPath)) {
            metadata = JSON.parse(fs.readFileSync(metadataPath, 'utf-8'));
        }
        
        metadata.server_runtime_path = path.join(distDir, 'svelte-server-runtime.js');
        metadata.server_bundle_size = stats.size;
        metadata.server_build_time = new Date().toISOString();
        
        fs.writeFileSync(metadataPath, JSON.stringify(metadata, null, 2));
        
        console.log('📦 Server runtime metadata updated');
        
    } catch (error) {
        console.error('Failed to bundle Svelte server runtime:', error);
        process.exit(1);
    }
}

// Run the bundler
bundleSvelteServerRuntime();
