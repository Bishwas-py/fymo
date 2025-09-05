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
    
    def transform_client_js_for_hydration(self, client_js: str, props: Dict[str, Any]) -> str:
        """Transform compiled Svelte client JS for proper hydration with scope handling"""
        
        # Properly escape the client JS for embedding in JavaScript
        # We need to handle backticks and other special characters
        client_js_escaped = (client_js
            .replace('\\', '\\\\')  # Escape backslashes first
            .replace('`', '\\`')     # Escape backticks
            .replace('${', '\\${')   # Escape template literal syntax
        )
        
        hydration_code = f"""
// Import Svelte client runtime from same server
import * as $ from '/assets/svelte/client/index.js';

// Get target and props
const target = document.getElementById('svelte-app');
const $$props = {json.dumps(props)};

// Store the component source as a properly escaped string
const componentSource = `{client_js_escaped}`;

try {{
    // Remove module-specific imports
    let processedCode = componentSource
        .replace(/import 'svelte\\/internal\\/disclose-version';?\\s*/g, '')
        .replace(/import \\* as \\$ from 'svelte\\/internal\\/client';?\\s*/g, '');
    
    // Extract the component function name
    const componentMatch = processedCode.match(/export default function (\\w+)/);
    const componentName = componentMatch ? componentMatch[1] : null;
    
    if (!componentName) {{
        throw new Error('Could not find component function name');
    }}
    
    console.log('Found component:', componentName);
    
    // Make $ available globally for the component
    window.$ = $;
    window.Posts = {{}};  // Create Posts object for FILENAME assignment
    
    // Create a new Function with the component code
    // This approach avoids issues with template literals in eval
    const createComponent = new Function('$', 'Posts', `
        // Remove export statement and define the component
        ${{processedCode.replace(/export default function/, 'function')}}
        
        // Return the component function
        return ${{componentName}};
    `);
    
    // Get the component constructor
    const Component = createComponent($, window.Posts);
    
    if (Component && typeof Component === 'function') {{
        // Clear server-rendered content for clean client-side hydration
        target.innerHTML = '';
        
        // Mount the component
        Component(target, $$props);
        
        console.log('✅ Svelte 5 component hydrated successfully');
    }} else {{
        throw new Error('Component is not a function');
    }}
}} catch (error) {{
    console.error('Hydration failed:', error);
    console.error('Component source preview:', componentSource.substring(0, 200) + '...');
    
    // Try an alternative approach using direct eval with proper scoping
    try {{
        console.log('Attempting alternative hydration approach...');
        
        // Make runtime available globally
        window.$ = $;
        window.Posts = {{}};
        
        // Process the code to remove imports and exports
        const cleanCode = componentSource
            .replace(/import 'svelte\\/internal\\/disclose-version';?\\s*/g, '')
            .replace(/import \\* as \\$ from 'svelte\\/internal\\/client';?\\s*/g, '')
            .replace(/export default function (\\w+)/, 'window.__SvelteComponent = function $1');
        
        // Execute the cleaned code
        eval(cleanCode);
        
        // Get the component
        const Component = window.__SvelteComponent;
        
        if (Component && typeof Component === 'function') {{
            target.innerHTML = '';
            Component(target, $$props);
            console.log('✅ Alternative hydration successful');
            
            // Clean up
            delete window.__SvelteComponent;
        }} else {{
            throw new Error('Component not found on window.__SvelteComponent');
        }}
    }} catch (altError) {{
        console.error('Alternative hydration also failed:', altError);
        throw error;
    }}
}}
"""
        
        return hydration_code

    def __del__(self):
        """Cleanup resources"""
        # STPyV8 handles cleanup automatically with context managers
        pass