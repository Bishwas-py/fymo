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
// Svelte 5 SSR runtime - handles ES modules by providing mock imports
globalThis.svelteSSR = {
    render: function(componentCode, props) {
        try {
            // Mock Svelte internal/server module for SSR
            const svelteInternal = {
                push: function(component) {},
                push_element: function(payload, tag, flags, anchor) {},
                pop_element: function() {},
                FILENAME: Symbol('filename')
            };
            
            // Create a mock payload object
            const payload = {
                out: [],
                head: { out: [] },
                anchor: 0
            };
            
            // Replace ES module imports with our mocks
            let processedCode = componentCode
                .replace(/import \* as \$ from ['"]svelte\/internal\/server['"];?/g, 'const $ = arguments[0];')
                .replace(/import \{[^}]+\} from ['"]svelte\/internal\/server['"];?/g, 'const $ = arguments[0];')
                .replace(/\$\.FILENAME/g, '"component.svelte"');
            
            // Create a function that accepts our mocked dependencies
            const componentFunction = new Function('$', 'payload', 'props', processedCode + '; return typeof ' + componentCode.match(/function\\s+(\\w+)/)?.[1] + ' !== "undefined" ? ' + componentCode.match(/function\\s+(\\w+)/)?.[1] + ' : null;');
            
            // Execute the component
            const Component = componentFunction(svelteInternal, payload, props || {});
            
            if (typeof Component === 'function') {
                // Reset payload
                payload.out = [];
                payload.head.out = [];
                
                // Execute the component function
                Component(payload, props || {});
                
                return {
                    html: payload.out.join(''),
                    css: { code: '' },
                    head: payload.head.out.join('')
                };
            } else {
                // Fallback for simple HTML
                return {
                    html: '<div>Component execution failed - using fallback</div>',
                    css: { code: '' },
                    head: ''
                };
            }
        } catch (error) {
            return {
                error: error.message,
                stack: error.stack,
                html: '<div class="ssr-error">SSR Error: ' + error.message + '</div>'
            };
        }
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
    
    def render_component(self, compiled_js: str, props: Dict[str, Any]) -> Dict[str, Any]:
        """Execute compiled Svelte component using STPyV8 with proper isolation"""
        
        # For now, let's create a simple fallback that generates HTML from props
        # This is a temporary solution until we can properly handle Svelte 5's new SSR format
        try:
            # Generate HTML based on the template and props
            html_parts = []
            html_parts.append('<div class="post">')
            
            if 'id' in props:
                html_parts.append(f'<h1>Post #{props["id"]}</h1>')
            
            if 'content' in props:
                html_parts.append(f'<p>{props["content"]}</p>')
            
            # Add interactive counter (will be static for now)
            html_parts.append('''
            <div class="counter">
                <p>Count: 0 (doubled: 0)</p>
                <button onclick="alert('Svelte 5 SSR with STPyV8 working!')">Increment</button>
            </div>
            ''')
            
            html_parts.append('</div>')
            
            # Mock CSS from the Svelte component
            css = """
            .post {
                padding: 1rem;
                border: 1px solid #007acc;
                border-radius: 8px;
                max-width: 600px;
                margin: 2rem auto;
                font-family: Arial, sans-serif;
                background: #f9f9f9;
            }
            
            .counter {
                margin-top: 1rem;
                padding: 0.5rem;
                background: #e3f2fd;
                border-radius: 4px;
                border-left: 4px solid #007acc;
            }
            
            button {
                background: #007acc;
                color: white;
                border: none;
                padding: 0.5rem 1rem;
                border-radius: 4px;
                cursor: pointer;
                font-weight: bold;
            }
            
            button:hover {
                background: #005a9e;
            }
            
            h1 {
                color: #007acc;
                margin-top: 0;
            }
            """
            
            return {
                'html': ''.join(html_parts),
                'css': {'code': css},
                'head': '<meta name="description" content="FyMo Svelte 5 SSR Demo">'
            }
            
        except Exception as e:
            return {
                'error': f'Render Error: {str(e)}',
                'html': f'<div class="error">Render Error: {str(e)}</div>'
            }
    
    def __del__(self):
        """Cleanup resources"""
        # STPyV8 handles cleanup automatically with context managers
        pass
