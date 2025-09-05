import subprocess
import json
import tempfile
import os
from pathlib import Path
from typing import Dict, Any

class SvelteCompiler:
    def __init__(self):
        self.base_dir = Path(__file__).parent
        self.compiler_script = """
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
"""
    
    def _run_compiler(self, svelte_source: str, filename: str, target: str, dev: bool = True) -> Dict[str, Any]:
        """Run Svelte compiler via Node.js subprocess"""
        # Create temp file in project directory so it can find node_modules
        with tempfile.NamedTemporaryFile(mode='w', suffix='.mjs', delete=False, dir=self.base_dir) as f:
            f.write(self.compiler_script)
            script_path = f.name
        
        try:
            input_data = json.dumps({
                'source': svelte_source,
                'filename': filename,
                'target': target,
                'dev': dev
            })
            
            result = subprocess.run([
                'node', script_path, input_data
            ], capture_output=True, text=True, cwd=self.base_dir)
            
            if result.returncode == 0:
                return json.loads(result.stdout)
            else:
                return {
                    'success': False,
                    'error': f"Compiler process failed: {result.stderr}",
                    'stdout': result.stdout
                }
        finally:
            os.unlink(script_path)
    
    def compile_ssr(self, svelte_source: str, filename: str) -> Dict[str, Any]:
        """Compile Svelte component for server-side rendering"""
        return self._run_compiler(svelte_source, filename, 'ssr')
    
    def compile_dom(self, svelte_source: str, filename: str) -> Dict[str, Any]:
        """Compile Svelte component for client-side rendering"""
        return self._run_compiler(svelte_source, filename, 'dom')

