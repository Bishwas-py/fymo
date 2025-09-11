import subprocess
import json
import tempfile
import os
from pathlib import Path
from typing import Dict, Any, Optional

from fymo.core.component_resolver import ComponentResolver

class SvelteCompiler:
    """Compiles Svelte components using Node.js subprocess"""
    
    def __init__(self, project_root: Optional[Path] = None) -> None:
        self.base_dir: Path = Path(__file__).parent
        self.project_root = project_root or Path.cwd()
        self.component_resolver = ComponentResolver(self.project_root)
        self.compiler_script: str = """
import { compile } from 'svelte/compiler';

const input = JSON.parse(process.argv[2]);
try {
    const results = {};
    let mainResult = null;
    
    // Compile main component
    const mainCompileResult = compile(input.source, {
        filename: input.filename,
        generate: input.target,
        hydratable: true,
        dev: input.dev || false
    });
    
    mainResult = {
        js: mainCompileResult.js.code,
        css: mainCompileResult.css ? mainCompileResult.css.code : ''
    };
    
    // Compile imported components if any
    if (input.imported_components) {
        for (const [componentName, componentSource] of Object.entries(input.imported_components)) {
            const componentResult = compile(componentSource, {
                filename: componentName + '.svelte',
                generate: input.target,
                hydratable: true,
                dev: input.dev || false
            });
            
            results[componentName] = {
                js: componentResult.js.code,
                css: componentResult.css ? componentResult.css.code : ''
            };
        }
    }
    
    console.log(JSON.stringify({
        success: true,
        main: mainResult,
        components: results
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
        # Resolve component imports and NPM packages
        file_path = Path(filename)
        target_env = 'node' if target == 'ssr' else 'browser'
        processed_source, imported_components, bundled_packages = self.component_resolver.resolve_imports(svelte_source, file_path, target_env)
        
        # Create temp file in project directory so it can find node_modules
        with tempfile.NamedTemporaryFile(mode='w', suffix='.mjs', delete=False, dir=self.base_dir) as f:
            f.write(self.compiler_script)
            script_path = f.name
        
        try:
            input_data = json.dumps({
                'source': processed_source,
                'filename': filename,
                'target': target,
                'dev': dev,
                'imported_components': imported_components
            })
            
            result = subprocess.run([
                'node', script_path, input_data
            ], capture_output=True, text=True, cwd=self.base_dir)
            
            if result.returncode == 0:
                compile_result = json.loads(result.stdout)
                
                # Restructure result to maintain backward compatibility
                if compile_result.get('success'):
                    return {
                        'success': True,
                        'js': compile_result['main']['js'],
                        'css': compile_result['main']['css'],
                        'components': compile_result.get('components', {}),
                        'bundled_packages': bundled_packages
                    }
                else:
                    return compile_result
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

