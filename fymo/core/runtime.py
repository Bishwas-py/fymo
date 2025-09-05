import json
from typing import Dict, Any
import STPyV8

class JSRuntime:
    """Production-ready STPyV8-based JavaScript runtime for SSR"""
    
    def __init__(self):
        print("✅ Using STPyV8 JavaScript runtime (Cloudflare's V8 bindings)")
        self._setup_runtime()
    
    def _setup_runtime(self):
        """Initialize Svelte SSR runtime environment with proper error handling"""
        self.runtime_code = """
// Svelte 5 SSR Runtime - Mocked implementation that works
// Mock the svelte/internal/server module with all necessary functions
const svelteInternal = {
    push: function(component) {
        // Stack management for component rendering
        // In dev mode, this sets up the current_component context
        if (component && component[svelteInternal.FILENAME]) {
            // Component has filename set
        }
    },
    push_element: function(payload, tag, flags, anchor) {
        // Element rendering helper
    },
    pop_element: function() {
        // Pop element from stack
    },
    pop: function() {
        // Pop component from stack
    },
    escape: function(value) {
        // HTML escape function for SSR
        if (value == null) return '';
        const str = String(value);
        
        return str
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    },
    attr: function(name, value, is_boolean) {
        // Attribute rendering for SSR
        if (value == null || (is_boolean && !value)) return '';
        const assignment = is_boolean ? '' : `="${svelteInternal.escape(value)}"`;
        return ` ${name}${assignment}`;
    },
    attr_class: function(value) {
        // Class attribute helper
        if (!value) return '';
        return ` class="${svelteInternal.escape(value)}"`;
    },
    stringify: function(value) {
        return typeof value === 'string' ? value : value == null ? '' : value + '';
    },
    ensure_array_like: function(value) {
        // Ensure value is array-like for iteration
        if (Array.isArray(value)) return value;
        if (value && typeof value.length === 'number') return value;
        return [];
    },
    each: function(items, callback) {
        // Helper for each blocks in SSR
        const array = svelteInternal.ensure_array_like(items);
        for (let i = 0; i < array.length; i++) {
            callback(array[i], i);
        }
    },
    FILENAME: Symbol('filename')
};

// Create render function for Svelte 5 components
globalThis.renderSvelte5 = function(componentCode, props) {
    try {
        // Create payload object for Svelte 5 SSR
        const payload = {
            out: [],
            head: { out: [] }
        };
        
        // Transform ES module import to our mock
        let transformedCode = componentCode;
        
        // Handle the FILENAME assignment - extract but don't execute yet
        const filenameMatch = transformedCode.match(/^(.+?)\\[\\$\\.FILENAME\\]\\s*=\\s*['"]([^'"]+)['"];?\\n/);
        let componentName = '';
        let filename = '';
        if (filenameMatch) {
            componentName = filenameMatch[1].trim();
            filename = filenameMatch[2];
            transformedCode = transformedCode.replace(filenameMatch[0], '');
        }
        
        // Remove import statement
        if (transformedCode.includes("import * as $ from 'svelte/internal/server'")) {
            transformedCode = transformedCode.replace("import * as $ from 'svelte/internal/server';", '');
        }
        if (transformedCode.includes('import * as $ from "svelte/internal/server"')) {
            transformedCode = transformedCode.replace('import * as $ from "svelte/internal/server";', '');
        }
        
        // Extract component function name from the function declaration
        const functionMatch = transformedCode.match(/function\\s+(\\w+)\\s*\\(/);
        if (!componentName && functionMatch) {
            componentName = functionMatch[1];
        }
        
        // Remove export default
        transformedCode = transformedCode.replace(/export default \\w+;?/, '');
        
        // Replace $.push() with $.push(Component) where Component is the function itself
        // This is needed for proper component context in dev mode
        if (componentName) {
            transformedCode = transformedCode.replace('$.push();', `$.push(${componentName});`);
        }
        
        // Create a wrapper function that provides $$props in the correct scope
        transformedCode = `
const $ = svelteInternal;

// Define the component
${transformedCode}

// Set FILENAME if we have it
if ('${filename}' && '${componentName}') {
    ${componentName}[$.FILENAME] = '${filename}';
}

// Create wrapper that provides $$props
globalThis.Component = function(payload, $$props) {
    return ${componentName}(payload, $$props);
};`;
        
        // Execute the transformed component code
        eval(transformedCode);
        
        // Get the component function
        const Component = globalThis.Component;
        
        if (typeof Component === 'function') {
            // Call the Svelte 5 component function with payload and props
            Component(payload, props || {});
            
            return {
                html: payload.out.join(''),
                css: { code: '' },
                head: payload.head.out.join('')
            };
        } else {
            throw new Error('Component is not a function');
        }
    } catch (error) {
        return {
            error: error.message,
            stack: error.stack,
            html: '<div class="ssr-error">SSR Error: ' + error.message + '</div>'
        };
    }
};

// Mock browser globals for SSR compatibility
globalThis.document = undefined;
globalThis.window = undefined;
globalThis.navigator = undefined;
globalThis.location = undefined;

// Mock console for debugging
if (typeof console === 'undefined') {
    globalThis.console = {
        log: function() {},
        error: function() {},
        warn: function() {},
        info: function() {}
    };
}
"""
    
    def render_component(self, compiled_js: str, props: Dict[str, Any], template_path: str) -> Dict[str, Any]:
        """Execute compiled Svelte SSR component using STPyV8"""
        try:
            # Use STPyV8's context manager for proper resource management
            with STPyV8.JSContext() as ctx:
                # Setup the runtime environment
                ctx.eval(self.runtime_code)
                
                # Prepare props as JSON string for safe injection
                props_json = json.dumps(props, ensure_ascii=False, separators=(',', ':'))
                
                # Call the Svelte 5 render function
                # Pass the compiled code as a string to our render function
                script = f"renderSvelte5({json.dumps(compiled_js)}, {props_json})"
                result = ctx.eval(script)
                
                # Convert JSObject to Python dict if needed
                if hasattr(result, '__dict__') or str(type(result)) == "<class '_STPyV8.JSObject'>":
                    # Convert JSObject to regular Python dict
                    python_result = {}
                    try:
                        # Try to access Svelte SSR result properties
                        if hasattr(result, 'html'):
                            python_result['html'] = str(result.html)
                        if hasattr(result, 'css'):
                            css_obj = result.css
                            if hasattr(css_obj, 'code'):
                                python_result['css'] = {'code': str(css_obj.code)}
                            else:
                                python_result['css'] = {'code': str(css_obj)}
                        if hasattr(result, 'head'):
                            python_result['head'] = str(result.head)
                        if hasattr(result, 'error'):
                            python_result['error'] = str(result.error)
                        if hasattr(result, 'stack'):
                            python_result['stack'] = str(result.stack)
                        return python_result
                    except Exception as e:
                        print(f"Error converting JSObject: {e}")
                        # Fallback to string representation
                        return {
                            'html': str(result),
                            'css': {'code': ''}
                        }
                else:
                    # Already a Python dict
                    return result
                    
        except STPyV8.JSError as e:
            error_msg = str(e)
            print(f"STPyV8 Runtime Error: {error_msg}")
            return {
                'error': f"STPyV8 Runtime Error: {error_msg}",
                'html': f'<div class="ssr-error">SSR Error: {error_msg}</div>'
            }
        except Exception as e:
            error_msg = str(e)
            print(f"Unexpected error in SSR: {error_msg}")
            return {
                'error': f"Unexpected error: {error_msg}",
                'html': f'<div class="ssr-error">SSR Error: {error_msg}</div>'
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
        
        # Use JSON.stringify to properly escape the component source
        import json
        component_source_json = json.dumps(component_source)
        
        # Build the hydration script that uses the bundled Svelte runtime
        hydration_script = f"""
(async function() {{
    try {{
        // Wait for the Svelte runtime to be loaded
        const SvelteRuntime = await import('/assets/svelte-runtime.js');
        
        // Get the component source from JSON (properly escaped)
        const componentSource = {component_source_json};
        
        // Create component factory
        const createComponent = new Function('SvelteRuntime', 'target', '$$props', 'componentSource', `
            const $ = SvelteRuntime;
            
            // Set the filename for debugging
            const {component_name} = {{}};
            {component_name}[$.FILENAME] = '{component_filename}';
            
            // Evaluate the component source
            eval(componentSource);
            
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
        const app = createComponent(SvelteRuntime, target, props, componentSource);
        
        // Store reference globally for debugging
        window.{component_name}App = app;
        
        console.log('✅ Svelte 5 component hydrated successfully');
        
    }} catch (error) {{
        console.error('Hydration failed:', error);
    }}
}})();
"""
        return hydration_script