"""
Refactored runtime using utility modules
"""

import json
from typing import Dict, Any
import STPyV8

from .utils import (
    # JS Transform Utils
    extract_filename_from_component,
    remove_es_module_imports,
    
    # JSON Utils
    safe_json_dumps,
    escape_js_for_embedding,
    prepare_props_json,
    
    # V8 Context Utils
    setup_console_mock,
    setup_browser_globals_mock,
    convert_js_object_to_dict,
    print_js_errors,
    is_js_object,
    
    # Runtime Templates
    get_commonjs_setup,
    get_server_runtime_wrapper,
    get_hydration_template,
    
    # Path Utils
    get_server_runtime_path,
    load_file_content,
    extract_component_name_from_path,
    
    # Error Utils
    format_ssr_error,
    print_ssr_error,
    create_js_error_response
)


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
            # Build the complete runtime code
            self.runtime_code = self._build_runtime_code(server_runtime)
            print("✅ Loaded real Svelte server runtime")
        else:
            # Server runtime is required
            raise RuntimeError(
                "Svelte server runtime not found. Please run 'fymo build-runtime' to generate it."
            )
    
    def _load_real_server_runtime(self):
        """Load the real Svelte server runtime if available"""
        server_runtime_path = get_server_runtime_path()
        return load_file_content(server_runtime_path)
    
    def _build_runtime_code(self, server_runtime: str) -> str:
        """Build the complete runtime code with all components"""
        
        # Combine all runtime components
        runtime_parts = [
            setup_console_mock(),
            get_commonjs_setup(),
            server_runtime,
            self._get_runtime_initialization(),
            self._get_render_svelte5_function(),
            setup_browser_globals_mock()
        ]
        
        return '\n'.join(runtime_parts)
    
    
    def _get_runtime_initialization(self) -> str:
        """Get the runtime initialization code"""
        return """
// Now extract the exported SvelteServer from module.exports
// Check if it's already defined to avoid redeclaration
if (!globalThis.SvelteServer) {
    const SvelteServer = module.exports;
    globalThis.SvelteServer = SvelteServer;
    globalThis.$ = SvelteServer;
} else {
    // Already loaded, just ensure $ is set
    globalThis.$ = globalThis.SvelteServer;
}

// Verify the runtime loaded correctly
if (!globalThis.$) {
    throw new Error('Failed to load Svelte server runtime');
}

"""
    
    def _get_render_svelte5_function(self) -> str:
        """Get the renderSvelte5 function using utility templates"""
        # Get the server wrapper template and prepare it for JavaScript injection
        server_wrapper_template = get_server_runtime_wrapper("COMPONENT_NAME_PLACEHOLDER", "FILENAME_PLACEHOLDER")
        # Escape the template for JavaScript string literal and fix the component code placeholder
        escaped_template = server_wrapper_template.replace('`', '\\`').replace('${COMPONENT_CODE}', '${componentCode}')
        
        return """
// Additional setup for real Svelte server runtime
globalThis.renderSvelte5 = function(componentCode, props) {
    try {
        const [componentName, filename, cleanedCode] = extractComponentInfo(componentCode);
        
        if (!globalThis.$) {
            throw new Error('Svelte server runtime not available');
        }
        
        const wrapperCode = createServerWrapper(componentName, filename, cleanedCode);
        eval(wrapperCode);
        
        return globalThis.renderComponent(props);
    } catch (error) {
        return {
            error: error.message,
            stack: error.stack,
            html: '<div class="ssr-error">SSR Error: ' + error.message + '</div>'
        };
    }
};

function extractComponentInfo(componentCode) {
    let transformedCode = componentCode;
    let componentName = '';
    let filename = '';
    
    const filenameMatch = transformedCode.match(/^(.+?)\\[\\$\\.FILENAME\\]\\s*=\\s*['"]([^'"]+)['"];?\\n/);
    if (filenameMatch) {
        componentName = filenameMatch[1].trim();
        filename = filenameMatch[2];
        transformedCode = transformedCode.replace(filenameMatch[0], '');
    }
    
    // ES module imports are now cleaned in Python before reaching here
    
    const functionMatch = transformedCode.match(/function\\s+(\\w+)\\s*\\(/);
    if (!componentName && functionMatch) {
        componentName = functionMatch[1];
    }
    
    transformedCode = transformedCode.replace(/export default \\w+;?/, '');
    
    return [componentName, filename, transformedCode];
}

function createServerWrapper(componentName, filename, componentCode) {
    return createServerWrapperTemplate(componentName, filename, componentCode);
}

function createServerWrapperTemplate(componentName, filename, componentCode) {
    const template = `""" + escaped_template + """`;
    return template.replace(/COMPONENT_NAME_PLACEHOLDER/g, componentName)
                  .replace(/FILENAME_PLACEHOLDER/g, filename);
}
"""
    
    def render_component(self, compiled_js: str, props: Dict[str, Any], template_path: str, controller=None) -> Dict[str, Any]:
        """Execute compiled Svelte SSR component using STPyV8"""
        try:
            # Use STPyV8's context manager for proper resource management
            with STPyV8.JSContext() as ctx:
                # Setup the runtime environment
                ctx.eval(self.runtime_code)
                
                # Note: getContext() is now handled server-side and passed as props
                # Setup getDoc() function for components
                if controller and hasattr(controller, 'getDoc') and callable(getattr(controller, 'getDoc')):
                    try:
                        doc_data = controller.getDoc()
                        doc_json = json.dumps(doc_data)
                        ctx.eval(f"globalThis.getDoc = function() {{ return {doc_json}; }};")
                    except Exception as e:
                        print(f"Error setting up getDoc: {e}")
                        ctx.eval("globalThis.getDoc = function() { return {}; };")
                
                # Clean ES module imports before passing to JavaScript
                cleaned_js = remove_es_module_imports(compiled_js)
                
                # Prepare props as JSON string for safe injection
                props_json = prepare_props_json(props)
                
                # Call the Svelte 5 render function
                script = f"renderSvelte5({safe_json_dumps(cleaned_js)}, {props_json})"
                result = ctx.eval(script)
                
                # Print any JavaScript errors
                print_js_errors(ctx)
                
                # Convert JSObject to Python dict if needed
                if is_js_object(result):
                    return convert_js_object_to_dict(result)
                else:
                    # Already a Python dict
                    return result
                    
        except STPyV8.JSError as e:
            error_msg = str(e)
            print(f"STPyV8 Runtime Error: {error_msg}")
            return create_js_error_response(error_msg)
            
        except Exception as e:
            error_msg = str(e)
            print_ssr_error(error_msg)
            
            # Try to get any errors before the exception
            try:
                if 'ctx' in locals():
                    print_js_errors(ctx)
            except:
                pass
            
            return format_ssr_error(e)

    def transform_client_js_for_hydration(self, compiled_js: str, template_path: str, context_data: Dict = None, doc_data: Dict = None) -> str:
        """
        Transform compiled Svelte client JS for browser hydration.
        This version uses the actual Svelte runtime bundled with esbuild.
        """
        # Clean the JavaScript code
        cleaned_js = remove_es_module_imports(compiled_js)
        
        # Extract component information using utility
        component_name, component_filename, _ = extract_filename_from_component(cleaned_js)
        
        # Use template path as fallback for filename
        if not component_filename and template_path:
            component_filename = template_path
        elif not component_filename:
            component_filename = 'component.svelte'
        
        # Extract component name from path if not found
        if not component_name:
            component_name = extract_component_name_from_path(template_path)
        
        # Escape the cleaned JS for JSON embedding
        client_js_escaped = escape_js_for_embedding(cleaned_js)
        
        # Generate hydration code using template with context data
        return get_hydration_template(component_name, component_filename, client_js_escaped, context_data, doc_data)
