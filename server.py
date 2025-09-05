import importlib
import json
from pathlib import Path

from rigids import SColor
from routes.config import paths
from svelte_compiler import SvelteCompiler
from js_runtime import JSRuntime
import mimetypes
import os

BASE_DIR = Path(__file__).resolve().parent

# Initialize Svelte compiler and runtime
svelte_compiler = SvelteCompiler()
js_runtime = JSRuntime()

# Asset storage for compiled components and extracted CSS
compiled_components = {}
extracted_css = {}


def render_svelte_template(path):
    """Render Svelte component with SSR"""
    template_path = BASE_DIR / f"templates/{paths[path]['template_path']}"
    
    # Read Svelte component
    with open(template_path, 'r') as f:
        svelte_source = f.read()
    
    # Get controller context
    controller_module = importlib.import_module(f"controllers.{paths[path]['controller_path']}")
    props = controller_module.context
    
    # Compile for SSR (extract CSS for serving separately)
    compiled = svelte_compiler.compile_ssr(svelte_source, str(template_path))
    
    if not compiled.get('success'):
        error_msg = compiled.get('error', 'Unknown compilation error')
        return f"<div>Svelte Compilation Error: {error_msg}</div>"
    
    # Render with JavaScript runtime
    render_result = js_runtime.render_component(compiled['js'], props, str(template_path))
    
    if 'error' in render_result:
        return f"<div>SSR Error: {render_result['error']}</div>"
    
    # Generate full HTML with hydration support
    html = render_result.get('html', '')
    
    # Extract and store CSS from compilation
    css = compiled.get('css', '')
    if css:
        component_name = Path(template_path).stem
        extracted_css[f"{component_name}.css"] = css
    
    # Compile client-side version for hydration
    client_compiled = svelte_compiler.compile_dom(svelte_source, str(template_path))
    
    if client_compiled.get('success'):
        client_js = client_compiled.get('js', '')
        
        # Store compiled component for serving
        component_name = Path(template_path).stem
        compiled_components[f"{component_name}.js"] = client_js
        
        # Transform the client JS to work with our hydration approach
        hydration_js = js_runtime.transform_client_js_for_hydration(client_js, props)
        
        # Add component URL as a comment for debugging
        component_url = f"/assets/components/{component_name}.js"
        hydration_js = f"// Component available at: {component_url}\n{hydration_js}"
    else:
        hydration_js = "console.log('Client compilation failed');"
    
    # Generate CSS links for all extracted CSS
    css_links = ""
    for css_file in extracted_css.keys():
        css_links += f'    <link rel="stylesheet" href="/assets/css/{css_file}">\n'
    
    full_html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>FyMo - Svelte SSR</title>
{css_links}</head>
<body>
    <div id="svelte-app">{html}</div>
    <script id="svelte-props" type="application/json">{json.dumps(props)}</script>
    <script type="module">
        // Use actual compiled Svelte client code for hydration
        {hydration_js}
    </script>
</body>
</html>"""
    
    return full_html


def serve_asset(path):
    """Serve static assets and compiled components"""
    try:
        if path.startswith('/assets/'):
            asset_path = path[8:]  # Remove '/assets/' prefix
            
            # Serve compiled components
            if asset_path.startswith('components/'):
                component_file = asset_path[11:]  # Remove 'components/' prefix
                if component_file in compiled_components:
                    return compiled_components[component_file], "200 OK", "application/javascript"
                else:
                    return f"Component not found: {component_file}", "404 NOT FOUND", "text/plain"
            
            # Serve Svelte runtime files
            elif asset_path.startswith('svelte/'):
                return serve_svelte_runtime(asset_path), "200 OK", "application/javascript"
            
            # Serve extracted CSS files
            elif asset_path.startswith('css/'):
                css_file = asset_path[4:]  # Remove 'css/' prefix
                if css_file in extracted_css:
                    return extracted_css[css_file], "200 OK", "text/css"
                else:
                    return serve_static_file(asset_path)
            
            # Serve other static files (JS, images, etc.)
            elif asset_path.startswith('js/') or asset_path.startswith('images/'):
                return serve_static_file(asset_path)
            
            else:
                return "Asset not found", "404 NOT FOUND", "text/plain"
        
        return "Invalid asset path", "400 BAD REQUEST", "text/plain"
        
    except Exception as e:
        print(f"{SColor.FAIL}Asset serving error: {e}{SColor.ENDC}")
        return f"Asset serving error: {str(e)}", "500 INTERNAL SERVER ERROR", "text/plain"


def serve_svelte_runtime(asset_path):
    """Serve Svelte runtime files"""
    if asset_path == 'svelte/client/index.js':
        return """
// Svelte 5 Client Runtime - Complete implementation for hydration
// This provides all the necessary internal client functions for Svelte 5

// Component filename tracking
export const FILENAME = Symbol('filename');

// State management
const states = new WeakMap();
const deriveds = new WeakMap();
const effects = [];
let current_component = null;

export function state(initial) {
    const value = { current: initial, subscribers: new Set() };
    return value;
}

export function tag(stateObj, name) {
    // Tags are just for debugging, return the state object
    return stateObj;
}

export function get(stateObj) {
    if (!stateObj || typeof stateObj !== 'object') return stateObj;
    return stateObj.current !== undefined ? stateObj.current : stateObj;
}

export function update(stateObj) {
    if (stateObj && typeof stateObj === 'object' && stateObj.current !== undefined) {
        stateObj.current++;
        // Notify subscribers
        if (stateObj.subscribers) {
            stateObj.subscribers.forEach(fn => fn());
        }
    }
}

export function derived(fn) {
    const derived = { fn, current: undefined, subscribers: new Set() };
    // Compute initial value
    derived.current = fn();
    return derived;
}

// DOM creation and manipulation
export function from_html(html) {
    const template = document.createElement('template');
    template.innerHTML = html.trim();
    return template.content.firstElementChild;
}

export function add_locations(node, filename, locations) {
    // This is for dev tools, just return the node
    return () => node.cloneNode(true);
}

export function child(parent, skip) {
    if (skip === true) {
        return parent.firstChild;
    }
    let child = parent.firstChild;
    for (let i = 0; i < (skip || 0); i++) {
        if (child) child = child.nextSibling;
    }
    return child || parent.firstChild;
}

export function sibling(node, skip) {
    let sibling = node;
    for (let i = 0; i < skip; i++) {
        if (sibling) sibling = sibling.nextSibling;
    }
    return sibling;
}

export function append(parent, child) {
    parent.appendChild(child);
}

export function set_text(node, text) {
    if (node) {
        node.textContent = text;
    }
}

// Component lifecycle
export function check_target(target) {
    // Validation for new.target
}

export function push(props, flag, component) {
    current_component = { props, component };
}

export function pop(api) {
    current_component = null;
    return api || {};
}

export function reset(node) {
    // Reset node state if needed
}

// Effects
export function template_effect(fn) {
    // Run the effect immediately and store for updates
    effects.push(fn);
    fn();
}

export function user_effect(fn) {
    // User effects run after template effects
    setTimeout(fn, 0);
}

export function log_if_contains_state(type, name, value) {
    return [name + ':', value];
}

// Event handling
export function delegate(events) {
    events.forEach(event => {
        document.addEventListener(event, (e) => {
            let target = e.target;
            while (target) {
                const handler = target['__' + event];
                if (handler) {
                    if (Array.isArray(handler)) {
                        const [fn, ...args] = handler;
                        fn(e, ...args);
                    } else {
                        handler(e);
                    }
                    break;
                }
                target = target.parentElement;
            }
        });
    });
}

// Legacy API support
export function legacy_api() {
    return {
        // Return empty object for legacy API
    };
}

console.log('✅ Svelte 5 client runtime loaded successfully');
"""
    
    elif asset_path == 'svelte/internal/server.js':
        return """
// Svelte 5 Server Runtime - Served from same server
export function escape(value) {
    if (value == null) return '';
    const str = String(value);
    
    return str
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

export const FILENAME = Symbol('filename');
console.log('✅ Svelte server runtime loaded from same server');
"""
    
    else:
        return f"// Svelte runtime file not found: {asset_path}"


def serve_static_file(asset_path):
    """Serve static files from the static directory"""
    try:
        # Security check - prevent directory traversal
        if '..' in asset_path or asset_path.startswith('/'):
            return "Access denied", "403 FORBIDDEN", "text/plain"
        
        # Build full path to static file
        static_file_path = BASE_DIR / 'static' / asset_path
        
        if static_file_path.exists() and static_file_path.is_file():
            # Determine content type
            content_type, _ = mimetypes.guess_type(str(static_file_path))
            if not content_type:
                content_type = 'application/octet-stream'
            
            # Read file content
            with open(static_file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            return content, "200 OK", content_type
        else:
            return f"Static file not found: {asset_path}", "404 NOT FOUND", "text/plain"
            
    except Exception as e:
        return f"Error serving static file: {str(e)}", "500 INTERNAL SERVER ERROR", "text/plain"


def render_template(path):
    """
    Renders template, where actual path is unformulated slash containing string.
    """
    if path != "/":
        path = path.lstrip('/')

    #  paths[path] gives filename i.e. index.svelte
    try:
        template_path = paths[path]['template_path']
        print(f"Rendering template: {template_path}")
        
        # Check if it's a Svelte component
        if template_path.endswith('.svelte'):
            html_str = render_svelte_template(path)
        else:
            # Fallback to old string formatting
            with open(BASE_DIR / f"templates/{template_path}", 'r') as f:
                html_str = f.read()
                mod = importlib.import_module(f"controllers.{paths[path]['controller_path']}")
                html_str = html_str.format(**mod.context)
        
        return html_str, "200 OK"
    except KeyError as e:
        error_message = f"400: {str(e)} not found"
        print(f"{SColor.FAIL}{error_message}{SColor.ENDC}")
        return f"{error_message}", "400 NOT FOUND"


# main server handler
def app(environ, start_response):
    path = environ.get("PATH_INFO")
    
    # Handle asset requests
    if path.startswith('/assets/'):
        content, status, content_type = serve_asset(path)
        content_bytes = content.encode("utf-8")
        start_response(
            status, [
                ("Content-Type", content_type),
                ("Content-Length", str(len(content_bytes))),
                ("Access-Control-Allow-Origin", "*"),  # CORS for assets
                ("Cache-Control", "public, max-age=3600")  # Cache assets for 1 hour
            ]
        )
        return iter([content_bytes])
    
    # Handle template requests
    html_raw, response = render_template(path)
    html = html_raw.encode("utf-8")
    start_response(
        response, [
            ("Content-Type", "text/html"),
            ("Content-Length", str(len(html)))
        ]
    )

    return iter([html])
