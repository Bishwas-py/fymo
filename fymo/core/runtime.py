import json
import subprocess
import tempfile
import os
from pathlib import Path
from typing import Dict, Any

class JSRuntime:
    """Production JavaScript runtime for SSR using Node.js subprocess with real Svelte"""
    
    def __init__(self):
        print("✅ Using Node.js subprocess for SSR with real Svelte runtime")
        self.base_dir = Path(__file__).parent.parent.parent  # Get to project root
    
    def render_component(self, compiled_js: str, props: Dict[str, Any], template_path: str) -> Dict[str, Any]:
        """Execute compiled Svelte SSR component using Node.js with real Svelte runtime"""
        
        # Create a Node.js ESM script that uses the actual Svelte internal/server module
        render_script = """
import * as $ from 'svelte/internal/server';

const props = JSON.parse(process.argv[2]);
const componentCode = process.argv[3];

// Debug logging
console.error('=== SSR Debug Info ===');
console.error('Props:', JSON.stringify(props));
console.error('Component code (first 200 chars):', componentCode.substring(0, 200));
console.error('$.FILENAME exists?', $.FILENAME !== undefined);

try {
    // Create a function that will execute the component code with $ in scope
    // We need to transform the component code to work in this context
    let transformedCode = componentCode;
    
    // Remove the import statement since we're providing $ 
    transformedCode = transformedCode.replace("import * as $ from 'svelte/internal/server';", '');
    transformedCode = transformedCode.replace('import * as $ from "svelte/internal/server";', '');
    
    // Handle the FILENAME assignment - extract the component name and filename
    const filenameMatch = transformedCode.match(/^(.+?)\\[\\$\\.FILENAME\\]\\s*=\\s*['"]([^'"]+)['"];?\\n/);
    let componentVarName = '';
    let filename = '';
    if (filenameMatch) {
        componentVarName = filenameMatch[1].trim();
        filename = filenameMatch[2];
        transformedCode = transformedCode.replace(filenameMatch[0], '');
        console.error('Found FILENAME assignment:', componentVarName, '[$.FILENAME] =', filename);
    }
    
    // Extract the function name
    const functionMatch = transformedCode.match(/function\\s+(\\w+)\\s*\\(/);
    const componentName = functionMatch ? functionMatch[1] : 'Component';
    console.error('Component name:', componentName);
    
    // Remove export default
    transformedCode = transformedCode.replace(/export default [^;]+;?/, '');
    
    // Fix the $.push() call to include the component function
    // The component calls $.push() at the beginning, but we need to pass the component itself
    transformedCode = transformedCode.replace('$.push();', `$.push(${componentName});`);
    
    // Create and execute the component
    const componentFactory = new Function('$', `
        ${transformedCode}
        return ${componentName};
    `);
    
    const Component = componentFactory($);
    console.error('Component type:', typeof Component);
    console.error('Component is function?', typeof Component === 'function');
    
    // CRITICAL: Set the FILENAME on the component BEFORE calling it
    if (filename && $.FILENAME) {
        Component[$.FILENAME] = filename;
        console.error('Set FILENAME on component:', filename);
    }
    
    // Create the SSR payload
    const payload = {
        out: [],
        head: { out: [] }
    };
    console.error('Created payload');
    
    // Call the component function
    if (typeof Component === 'function') {
        console.error('Calling component with payload and props...');
        try {
            // The component will call $.push() itself, so we just call it directly
            Component(payload, props);
            
            // Return the rendered HTML
            console.log(JSON.stringify({
                success: true,
                html: payload.out.join(''),
                head: payload.head.out.join(''),
                css: { code: '' }
            }));
        } catch (innerError) {
            console.error('Error during component execution:', innerError.message);
            console.error('Stack:', innerError.stack);
            throw innerError;
        }
    } else {
        throw new Error('Component is not a function');
    }
} catch (error) {
    console.error('Full error:', error.message);
    console.error('Error stack:', error.stack);
    console.log(JSON.stringify({
        success: false,
        error: error.message,
        stack: error.stack
    }));
}
"""
        
        try:
            # Create temp file for the render script (as .mjs for ES modules)
            with tempfile.NamedTemporaryFile(mode='w', suffix='.mjs', delete=False, dir=self.base_dir) as f:
                f.write(render_script)
                script_path = f.name
            
            try:
                # Prepare the data
                props_json = json.dumps(props)
                
                # Run the Node.js script with experimental modules support
                result = subprocess.run(
                    ['node', script_path, props_json, compiled_js],
                    capture_output=True,
                    text=True,
                    cwd=self.base_dir,
                    timeout=5
                )
                
                # Always print stderr for debugging
                if result.stderr:
                    print(f"Node.js stderr:\n{result.stderr}")
                    
                if result.returncode == 0:
                    try:
                        output = json.loads(result.stdout)
                        if output.get('success'):
                            return {
                                'html': output.get('html', ''),
                                'css': output.get('css', {'code': ''}),
                                'head': output.get('head', '')
                            }
                        else:
                            return {
                                'error': output.get('error', 'Unknown error'),
                                'html': f'<div class="ssr-error">SSR Error: {output.get("error", "Unknown error")}</div>'
                            }
                    except json.JSONDecodeError:
                        # If we can't parse JSON, return the raw output as error
                        print(f"Invalid JSON from Node.js stdout:\n{result.stdout}")
                        return {
                            'error': f"Invalid JSON response: {result.stdout}",
                            'html': f'<div class="ssr-error">SSR Error: Invalid response</div>'
                        }
                else:
                    error_msg = result.stderr or result.stdout
                    # Also print stderr for debugging
                    if result.stderr:
                        print(f"Node.js stderr:\n{result.stderr}")
                    return {
                        'error': f"Node.js process failed: {error_msg}",
                        'html': f'<div class="ssr-error">SSR Error: {error_msg}</div>'
                    }
                    
            finally:
                # Clean up temp file
                os.unlink(script_path)
                
        except subprocess.TimeoutExpired:
            return {
                'error': "SSR timeout",
                'html': '<div class="ssr-error">SSR Error: Rendering timeout</div>'
            }
        except Exception as e:
            return {
                'error': str(e),
                'html': f'<div class="ssr-error">SSR Error: {str(e)}</div>'
            }

    def transform_client_js_for_hydration(self, compiled_js: str, template_path: str) -> str:
        """
        Transform compiled Svelte client JS for browser hydration.
        This version uses the actual Svelte runtime bundled with esbuild.
        """
        # Extract just the filename from the template path
        from pathlib import Path
        component_filename = Path(template_path).name
        component_name = Path(template_path).stem.capitalize()
        
        # Process the component source to work with our bundled runtime
        # Remove all import statements since we're providing the runtime globally
        lines = compiled_js.split('\n')
        processed_lines = []
        
        for line in lines:
            # Skip import statements
            if line.strip().startswith('import ') or line.strip().startswith('import{'):
                continue
            # Skip the filename assignment at the top (we'll add it back later)
            if '$.FILENAME' in line and component_name in line:
                continue
            processed_lines.append(line)
        
        component_source = '\n'.join(processed_lines)
        
        # Replace export default with a variable assignment
        component_source = component_source.replace('export default function', 'const ComponentExport = function')
        
        # Build the hydration script that uses the bundled Svelte runtime
        hydration_script = f"""
(async function() {{
    try {{
        // Wait for the Svelte runtime to be loaded
        const SvelteRuntime = await import('/assets/svelte-runtime.js');
        
        // Create component factory
        const createComponent = new Function('SvelteRuntime', 'target', '$$props', `
            const $ = SvelteRuntime;
            
            // Set the filename for debugging
            const {component_name} = {{}};
            {component_name}[$.FILENAME] = '{component_filename}';
            
            // Component source (with imports removed)
            {component_source}
            
            // Use Svelte's mount function for hydration
            return $.mount(ComponentExport, {{
                target: target,
                props: $$props,
                hydrate: true
            }});
        `);
        
        // Get target element
        const target = document.getElementById('svelte-app');
        if (!target) {{
            console.error('Target element #svelte-app not found');
            return;
        }}
        
        // Get initial props from the page
        const propsElement = document.getElementById('svelte-props');
        const props = propsElement ? JSON.parse(propsElement.textContent) : {{}};
        
        console.log('Found component:', '{component_name}');
        
        // Create and hydrate the component
        const app = createComponent(SvelteRuntime, target, props);
        
        // Store reference globally for debugging
        window.{component_name}App = app;
        
        console.log('✅ Svelte 5 component hydrated successfully');
        
    }} catch (error) {{
        console.error('Hydration failed:', error);
        // Don't log component source to avoid escaping issues
    }}
}})();
"""
        return hydration_script