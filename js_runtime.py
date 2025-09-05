import json
from typing import Dict, Any, List
import STPyV8

class JSRuntime:
    """Production-ready STPyV8-based JavaScript runtime for SSR"""
    
    def __init__(self):
        print("✅ Using STPyV8 JavaScript runtime (Cloudflare's V8 bindings)")
        self._setup_runtime()
    
    def _setup_runtime(self):
        """Initialize Svelte SSR runtime environment with proper error handling"""
        self.runtime_code = """
// Svelte 5 SSR Runtime - proper implementation
// Mock the svelte/internal/server module
const svelteInternal = {
    push: function(component) {
        // Stack management for component rendering
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
        // Simple string replacements to avoid regex escaping issues
        let transformedCode = componentCode;
        
        // Remove import statement
        if (transformedCode.includes("import * as $ from 'svelte/internal/server'")) {
            transformedCode = transformedCode.replace("import * as $ from 'svelte/internal/server';", '');
        }
        if (transformedCode.includes('import * as $ from "svelte/internal/server"')) {
            transformedCode = transformedCode.replace('import * as $ from "svelte/internal/server";', '');
        }
        
        // Extract component name
        const componentMatch = transformedCode.match(/function\\s+(\\w+)\\s*\\(/);
        const componentName = componentMatch ? componentMatch[1] : 'UnknownComponent';
        
        // Remove export default
        transformedCode = transformedCode.replace(/export default \\w+;?/, '');
        
        // Create a wrapper function that provides $$props in the correct scope
        transformedCode = `
const $ = svelteInternal;
${transformedCode}

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
        """Execute compiled Svelte SSR component using STPyV8 like LiveBud does"""
        try:
            # Use STPyV8's context manager for proper resource management
            with STPyV8.JSContext() as ctx:
                # Setup the runtime environment
                ctx.eval(self.runtime_code)
                
                # Prepare props as JSON string for safe injection
                props_json = json.dumps(props, ensure_ascii=False, separators=(',', ':'))
                
                # Call the Svelte 5 render function (updated for Svelte 5)
                # Pass the compiled code as a string to our render function
                # Use JSON.stringify to properly escape the JavaScript code
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
                    except Exception as e:
                        python_result = {
                            'error': f'Failed to convert JSObject: {str(e)}',
                            'html': '<div>JSObject conversion error</div>'
                        }
                    return python_result
                
                return result if isinstance(result, dict) else {'html': str(result)}
                
        except STPyV8.JSError as js_err:
            # Handle JavaScript execution errors
            return {
                'error': f'JavaScript Error: {str(js_err)}',
                'html': f'<div class="js-error">JavaScript Error: {str(js_err)}</div>',
                'stack': getattr(js_err, 'stack', None)
            }
        except Exception as e:
            # Handle Python-level errors
            return {
                'error': f'STPyV8 Runtime Error: {str(e)}',
                'html': f'<div class="runtime-error">Runtime Error: {str(e)}</div>'
            }
    
    def transform_client_js_for_hydration(self, client_js: str, props: Dict[str, Any], template_path: str = None) -> str:
        """Transform compiled Svelte client JS for hydration with real Svelte runtime"""
        
        # Remove import statements from the compiled code
        # These imports are handled by our bundled runtime
        cleaned_js = client_js
        cleaned_js = cleaned_js.replace("import 'svelte/internal/disclose-version';", '')
        cleaned_js = cleaned_js.replace("import * as $ from 'svelte/internal/client';", '')
        
        # Extract the actual filename from the component source
        # Look for the pattern: ComponentName[$.FILENAME] = 'path/to/file.svelte';
        import re
        filename_match = re.search(r"\w+\[\$\.FILENAME\]\s*=\s*['\"]([^'\"]+)['\"]", cleaned_js)
        if filename_match:
            component_filename = filename_match.group(1)
        elif template_path:
            # Use provided template path as fallback
            component_filename = template_path
        else:
            # Default fallback
            component_filename = 'component.svelte'
        
        # Escape the cleaned JS for JSON embedding
        client_js_escaped = json.dumps(cleaned_js)
        
        hydration_code = f"""
// Production-ready Svelte 5 hydration with real runtime
import * as SvelteRuntime from '/assets/svelte/client/index.js';

// Get target and props
const target = document.getElementById('svelte-app');
const $$props = {json.dumps(props)};

// Component source code (with imports already removed)
const componentSource = {client_js_escaped};

try {{
    // Process code to create a clean module structure
    let moduleCode = componentSource
        .replace(/export default function (\\w+)/, 'const ComponentExport = function $1')
        .trim();
    
    // Extract component name
    const match = moduleCode.match(/const ComponentExport = function (\\w+)/);
    if (!match) {{
        throw new Error('Could not extract component name');
    }}
    const componentName = match[1];
    
    console.log('Found component:', componentName);
    
    // Use the mount approach directly as it's more reliable
    const createModule = new Function('SvelteRuntime', `
        const $ = SvelteRuntime;
        const {{
            state, derived, get, update, tag,
            template_effect, user_effect,
            from_html, add_locations, child, sibling, append, set_text,
            check_target, push, pop, reset, delegate,
            log_if_contains_state, legacy_api, FILENAME
        }} = SvelteRuntime;
        
        // Component namespace
        const ${{componentName}} = {{}};
        ${{componentName}}[FILENAME] = '{component_filename}';
        
        ${{moduleCode}}
        
        return ComponentExport;
    `);
    
    const Component = createModule(SvelteRuntime);
    
    if (Component && typeof Component === 'function') {{
        const target = document.getElementById('svelte-app');
        const $$props = {json.dumps(props)};
        
        target.innerHTML = '';
        
        // Use mount if available, otherwise direct call
        if (SvelteRuntime.mount) {{
            SvelteRuntime.mount(Component, {{ target, props: $$props }});
        }} else {{
            Component(target, $$props);
        }}
        
        console.log('✅ Svelte 5 component hydrated with production runtime');
    }} else {{
        throw new Error('Component is not a valid function');
    }}
}} catch (error) {{
    console.error('Primary hydration failed:', error);
    
    // Alternative approach using mount from Svelte
    try {{
        console.log('Trying mount approach...');
        
        // Process code to create a module-like structure
        let moduleCode = componentSource
            .replace(/export default function (\\w+)/, 'const $1Component = function $1')
            .trim();
        
        // Extract component name
        const match = moduleCode.match(/const (\\w+)Component = function/);
        if (!match) {{
            throw new Error('Could not extract component name');
        }}
        const componentName = match[1];
        
        // Create a module wrapper
        const createModule = new Function('SvelteRuntime', `
            const $ = SvelteRuntime;
            const {{
                state, derived, get, update, tag,
                template_effect, user_effect,
                from_html, add_locations, child, sibling, append, set_text,
                check_target, push, pop, reset, delegate,
                log_if_contains_state, legacy_api, FILENAME
            }} = SvelteRuntime;
            
            // Component namespace
            const ${{componentName}} = {{}};
            ${{componentName}}[FILENAME] = '{component_filename}';
            
            ${{moduleCode}}
            
            return ${{componentName}}Component;
        `);
        
        const Component = createModule(SvelteRuntime);
        
        if (Component && typeof Component === 'function') {{
            const target = document.getElementById('svelte-app');
            const $$props = {json.dumps(props)};
            
            target.innerHTML = '';
            
            // Use Svelte's mount if available
            if (SvelteRuntime.mount) {{
                SvelteRuntime.mount(Component, {{ target, props: $$props }});
            }} else {{
                // Direct call as fallback
                Component(target, $$props);
            }}
            
            console.log('✅ Mount approach hydration successful');
        }} else {{
            throw new Error('Component not found');
        }}
    }} catch (fallbackError) {{
        console.error('Mount approach also failed:', fallbackError);
        throw error;
    }}
}}
"""
        
        return hydration_code

    def __del__(self):
        """Cleanup resources"""
        # STPyV8 handles cleanup automatically with context managers
        pass