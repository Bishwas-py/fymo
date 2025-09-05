
import { compile } from 'svelte/compiler';

const input = JSON.parse(process.argv[2]);
try {
    const result = compile(input.source, {
        filename: input.filename,
        generate: input.target,
        hydratable: true,
        dev: input.dev || false
    });
    
    console.log(JSON.stringify({
        success: true,
        js: result.js.code,
        css: result.css ? result.css.code : ''
    }));
} catch (error) {
    console.log(JSON.stringify({
        success: false,
        error: error.message,
        stack: error.stack
    }));
}
