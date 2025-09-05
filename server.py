import importlib
import json
from pathlib import Path

from rigids import SColor
from routes.config import paths
from svelte_compiler import SvelteCompiler
from js_runtime import JSRuntime

BASE_DIR = Path(__file__).resolve().parent

# Initialize Svelte compiler and runtime
svelte_compiler = SvelteCompiler()
js_runtime = JSRuntime()


def render_svelte_template(path):
    """Render Svelte component with SSR"""
    template_path = BASE_DIR / f"templates/{paths[path]['template_path']}"
    
    # Read Svelte component
    with open(template_path, 'r') as f:
        svelte_source = f.read()
    
    # Get controller context
    controller_module = importlib.import_module(f"controllers.{paths[path]['controller_path']}")
    props = controller_module.context
    
    # Compile for SSR
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
    css = render_result.get('css', {}).get('code', '') or compiled.get('css', '')
    
    # Compile client-side version for hydration
    client_compiled = svelte_compiler.compile_dom(svelte_source, str(template_path))
    
    if client_compiled.get('success'):
        client_js = client_compiled.get('js', '')
        # Transform the client JS to work with our hydration approach
        hydration_js = js_runtime.transform_client_js_for_hydration(client_js, props)
    else:
        hydration_js = "console.log('Client compilation failed');"
    
    full_html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>FyMo - Svelte SSR</title>
    {f'<style>{css}</style>' if css else ''}
</head>
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
    html_raw, response = render_template(path)
    html = html_raw.encode("utf-8")
    start_response(
        response, [
            ("Content-Type", "text/html"),
            ("Content-Length", str(len(html)))
        ]
    )

    return iter([html])
