import json
import os
from typing import Dict, Any
import STPyV8

class JSRuntime:
    """Production-ready STPyV8-based JavaScript runtime for SSR"""
    
    def __init__(self):
        print("✅ Using STPyV8 JavaScript runtime (Cloudflare's V8 bindings)")
        self._setup_runtime()
    
    def _setup_runtime(self):
        """Initialize Svelte SSR runtime environment with proper error handling"""
        
        # Try to load real Svelte server runtime first
        server_runtime = self._load_real_server_runtime()
        
        if server_runtime:
            # Use the real Svelte server runtime
            # Setup a module.exports object for CommonJS
            self.runtime_code = """
// Setup minimal console for error tracking
const console = {
    log: function() {},  // Suppress logs in production
    error: function(...args) {
        const msg = args.map(a => String(a)).join(' ');
        if (!globalThis.__errors) globalThis.__errors = [];
        globalThis.__errors.push(msg);
    },
    warn: function() {}  // Suppress warnings in production
};
globalThis.console = console;

// Setup CommonJS environment for the server runtime
const module = { exports: {} };
const exports = module.exports;

""" + server_runtime + """

// Now extract the exported SvelteServer from module.exports
// Check if it's already defined to avoid redeclaration
if (!globalThis.SvelteServer) {
    const SvelteServer = module.exports;
    globalThis.SvelteServer = SvelteServer;
    globalThis.$ = SvelteServer;
    
    // Server runtime loaded successfully
} else {
    // Already loaded, just ensure $ is set
    globalThis.$ = globalThis.SvelteServer;
}

// Verify the runtime loaded correctly
if (!globalThis.$) {
    throw new Error('Failed to load Svelte server runtime');
}

// Additional setup for real Svelte server runtime
globalThis.renderSvelte5 = function(componentCode, props) {
    try {
        // Starting renderSvelte5 with real server runtime
        
        // Transform ES module import to use global $
        let transformedCode = componentCode;
        
        // Handle the FILENAME assignment
        const filenameMatch = transformedCode.match(/^(.+?)\\[\\$\\.FILENAME\\]\\s*=\\s*['"]([^'"]+)['"];?\\n/);
        let componentName = '';
        let filename = '';
        if (filenameMatch) {
            componentName = filenameMatch[1].trim();
            filename = filenameMatch[2];
            transformedCode = transformedCode.replace(filenameMatch[0], '');
            // Found component and filename
        }
        
        // Remove import statement
        transformedCode = transformedCode.replace(/import \\* as \\$ from ['"](svelte\\/internal\\/server)['"];?/g, '');
        
        // Extract component function name
        const functionMatch = transformedCode.match(/function\\s+(\\w+)\\s*\\(/);
        if (!componentName && functionMatch) {
            componentName = functionMatch[1];
            // Extracted component name from function
        }
        
        // Remove export default
        transformedCode = transformedCode.replace(/export default \\w+;?/, '');
        
        // Verify server runtime is available
        if (!globalThis.$) {
            throw new Error('Svelte server runtime not available');
        }
        
        // Create wrapper that uses the real Svelte server runtime render function
        transformedCode = `
// Use the real Svelte server runtime
const $ = globalThis.$ || globalThis.SvelteServer;

// Verify $ is available
if (!$) {
    throw new Error('Svelte server runtime not found');
}

// Define the component
${transformedCode}

// Set FILENAME if we have it
if ('${filename}' && '${componentName}' && $.FILENAME) {
    ${componentName}[$.FILENAME] = '${filename}';
    // FILENAME set for component
}

// Use the real Svelte render function
globalThis.renderComponent = function(props) {
    // Calling $.render with component and props
    
    try {
        // First try the standard render approach
        const result = $.render(${componentName}, { 
            props: props || {},
            context: new Map()  // Add context map
        });
        
        // Render successful
        
        return result;
    } catch (error) {
        // Standard render failed, trying fallback
        
        // The error is happening because push_element is trying to read
        // component[$.FILENAME] but the component context isn't set up properly
        // Let's try to debug what's happening
        
        // Check component properties for debugging
        
        // The real issue is that the render function expects the component
        // to have certain internal properties set up. Let's try a different approach:
        // Instead of calling render directly, we need to ensure the component
        // is properly wrapped with the necessary context
        
        // Create a wrapper that sets up the component properly
        const wrappedComponent = function(payload, props, slots, context) {
            // Ensure the component has the FILENAME symbol
            if (!${componentName}[$.FILENAME]) {
                ${componentName}[$.FILENAME] = '${filename}';
            }
            
            // Call the original component
            return ${componentName}(payload, props, slots, context);
        };
        
        // Copy over the FILENAME property
        wrappedComponent[$.FILENAME] = '${filename}';
        
        // Try render with wrapped component
        
        try {
            const result = $.render(wrappedComponent, {
                props: props || {},
                context: new Map()
            });
            
            // Wrapped render successful
            return result;
        } catch (wrapError) {
            // Both render approaches failed, using fallback
            
            // Final fallback: return an error message
            return {
                html: '<div class="ssr-error">SSR Error: ' + error.message + '</div>',
                head: '',
                css: { code: '' }
            };
        }
    }
};`;
        
        // Execute the transformed component code
        eval(transformedCode);
        
        // Call the render function with props
        const result = globalThis.renderComponent(props);
        return result;
    } catch (error) {
        // SSR rendering error
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
"""
            print("✅ Loaded real Svelte server runtime")
        else:
            # Fall back to mocked runtime
            print("⚠️ Using mocked Svelte server runtime (real runtime not found)")
            self.runtime_code = self._get_mocked_runtime()
    
    def _load_real_server_runtime(self):
        """Load the real Svelte server runtime if available"""
        try:
            # Get the path to the bundled server runtime
            bundler_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            server_runtime_path = os.path.join(bundler_dir, 'bundler', 'js', 'dist', 'svelte-server-runtime.js')
            
            if os.path.exists(server_runtime_path):
                with open(server_runtime_path, 'r') as f:
                    return f.read()
        except Exception as e:
            print(f"Failed to load server runtime: {e}")
        
        return None
    
    def _get_mocked_runtime(self):
        """Return the mocked Svelte server runtime as fallback"""
        return """
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

// Expose as global $ for compatibility
globalThis.$ = svelteInternal;
globalThis.SvelteServer = svelteInternal;

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
    
    def _get_errors_if_any(self, ctx):
        """Retrieve any errors from V8 context for debugging"""
        try:
            errors = ctx.eval("globalThis.__errors || []")
            if errors:
                for i in range(len(errors)):
                    error = ctx.eval(f"globalThis.__errors[{i}]")
                    print(f"[JS Error] {error}")
                # Clear errors after printing
                ctx.eval("globalThis.__errors = []")
        except:
            pass  # Silently ignore if we can't get errors
    
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
                
                # Check for any errors (only in development/debugging)
                self._get_errors_if_any(ctx)
                
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
            print(f"\n=== SSR Error ===")
            print(f"Unexpected error in SSR: {error_msg}")
            
            # Try to get any errors before the exception
            try:
                if 'ctx' in locals():
                    self._get_errors_if_any(ctx)
            except:
                pass
            
            import traceback
            stack = traceback.format_exc()
            print(f"Stack trace:\n{stack}")
            print("=== End SSR Error ===\n")
            
            return {
                'error': f"Unexpected error: {error_msg}",
                'html': f'<div class="ssr-error">SSR Error: {error_msg}</div>',
                'stack': stack
            }

    def transform_client_js_for_hydration(self, compiled_js: str, template_path: str) -> str:
        """
        Transform compiled Svelte client JS for browser hydration.
        This version uses the actual Svelte runtime bundled with esbuild.
        This is the WORKING version from the old commit!
        """
        # Remove import statements from the compiled code
        # These imports are handled by our bundled runtime
        cleaned_js = compiled_js
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
        
        # Extract just the filename from the path
        from pathlib import Path
        component_name = Path(template_path).stem.capitalize() if template_path else 'Component'
        
        # Escape the cleaned JS for JSON embedding - THIS IS THE KEY!
        # Use json.dumps to properly escape all special characters
        client_js_escaped = json.dumps(cleaned_js)
        
        # Get props for embedding
        # Note: props should be passed from the server, but for now we'll use empty
        props_json = '{}'
        
        hydration_code = f"""
// Production-ready Svelte 5 hydration with real runtime
import * as SvelteRuntime from '/assets/svelte-runtime.js';

// Get target and props
const target = document.getElementById('svelte-app');
const propsElement = document.getElementById('svelte-props');
const $$props = propsElement ? JSON.parse(propsElement.textContent) : {{}};

// Component source code (with imports already removed and properly escaped)
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