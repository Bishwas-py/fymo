"""
JavaScript template strings for runtime setup
"""


def get_commonjs_setup() -> str:
    """
    Get CommonJS environment setup code
    
    Returns:
        JavaScript code for CommonJS setup
    """
    return """
// Setup CommonJS environment for the server runtime
const module = { exports: {} };
const exports = module.exports;
"""


def get_server_runtime_wrapper(component_name: str, filename: str) -> str:
    """
    Get the wrapper code for server runtime rendering
    
    Args:
        component_name: Name of the Svelte component
        filename: Path to the component file
        
    Returns:
        JavaScript template for server rendering
    """
    return f"""
// Use the real Svelte server runtime
const $ = globalThis.$ || globalThis.SvelteServer;

// Verify $ is available
if (!$) {{
    throw new Error('Svelte server runtime not found');
}}

// Define the component
${{COMPONENT_CODE}}

// Set FILENAME if we have it
if ('{filename}' && '{component_name}' && $.FILENAME) {{
    {component_name}[$.FILENAME] = '{filename}';
}}

// Use the real Svelte render function
globalThis.renderComponent = function(props) {{
    try {{
        // First try the standard render approach
        const result = $.render({component_name}, {{ 
            props: props || {{}},
            context: new Map()
        }});
        
        return result;
    }} catch (error) {{
        // Standard render failed, trying fallback
        
        // Create a wrapper that sets up the component properly
        const wrappedComponent = function(payload, props, slots, context) {{
            // Ensure the component has the FILENAME symbol
            if (!{component_name}[$.FILENAME]) {{
                {component_name}[$.FILENAME] = '{filename}';
            }}
            
            // Call the original component
            return {component_name}(payload, props, slots, context);
        }};
        
        // Copy over the FILENAME property
        wrappedComponent[$.FILENAME] = '{filename}';
        
        try {{
            const result = $.render(wrappedComponent, {{
                props: props || {{}},
                context: new Map()
            }});
            
            return result;
        }} catch (wrapError) {{
            // Both render approaches failed, using fallback
            return {{
                html: '<div class="ssr-error">SSR Error: ' + error.message + '</div>',
                head: '',
                css: {{ code: '' }}
            }};
        }}
    }}
}};"""


def get_hydration_template(component_name: str, filename: str, escaped_code: str, context_data: dict = None, doc_data: dict = None) -> str:
    """
    Get the hydration template for client-side
    
    Args:
        component_name: Name of the component
        filename: Path to the component file
        escaped_code: Escaped JavaScript code
        context_data: Context data from server
        doc_data: Document metadata from server
        
    Returns:
        Complete hydration JavaScript code
    """
    # Prepare context and doc data as JSON
    import json
    context_json = "null" if context_data is None else json.dumps(context_data)
    doc_json = "null" if doc_data is None else json.dumps(doc_data)
    
    return f"""
// Production-ready Svelte 5 hydration with real runtime
import * as SvelteRuntime from '/assets/svelte-runtime.js';

// Setup client-side getDoc function
const docData = {doc_json};
globalThis.getDoc = function() {{
    return docData || {{}};
}};

// Get target and props
const target = document.getElementById('svelte-app');
const propsElement = document.getElementById('svelte-props');
const $$props = propsElement ? JSON.parse(propsElement.textContent) : {{}};

// Component source code (with imports already removed and properly escaped)
const componentSource = {escaped_code};

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
        ${{componentName}}[FILENAME] = '{filename}';
        
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
            ${{componentName}}[FILENAME] = '{filename}';
            
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

def get_render_svelte5_function() -> str:
    """
    Get the main renderSvelte5 function template
    
    Returns:
        JavaScript code for the renderSvelte5 function
    """
    return """
// Additional setup for real Svelte server runtime
globalThis.renderSvelte5 = function(componentCode, props) {
    try {
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
        }
        
        // Remove import statement
        transformedCode = transformedCode.replace(/import \\* as \\$ from ['"](svelte\\/internal\\/server)['"];?/g, '');
        
        // Extract component function name
        const functionMatch = transformedCode.match(/function\\s+(\\w+)\\s*\\(/);
        if (!componentName && functionMatch) {
            componentName = functionMatch[1];
        }
        
        // Remove export default
        transformedCode = transformedCode.replace(/export default \\w+;?/, '');
        
        // Verify server runtime is available
        if (!globalThis.$) {
            throw new Error('Svelte server runtime not available');
        }
        
        // Create wrapper that uses the real Svelte server runtime render function
        transformedCode = getServerRuntimeWrapper(componentName, filename).replace('{COMPONENT_CODE}', transformedCode);
        
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
            html: getErrorFallbackHtml(error.message)
        };
    }
};
"""
