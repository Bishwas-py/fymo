"""
V8/STPyV8 context utilities
"""

from typing import Dict, Any, List


def setup_console_mock() -> str:
    """
    Return JavaScript code for mocking console in V8 context
    
    Returns:
        JavaScript code string for console setup
    """
    return """
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
"""


def setup_browser_globals_mock() -> str:
    """
    Return JavaScript code for mocking browser globals
    
    Returns:
        JavaScript code string for browser globals
    """
    return """
// Mock browser globals for SSR compatibility
globalThis.document = undefined;
globalThis.window = undefined;
globalThis.navigator = undefined;
globalThis.location = undefined;
"""


def convert_js_object_to_dict(js_obj) -> Dict[str, Any]:
    """
    Convert STPyV8 JSObject to Python dict
    
    Args:
        js_obj: JSObject from STPyV8
        
    Returns:
        Python dictionary representation
    """
    python_result = {}
    
    try:
        # Try to access Svelte SSR result properties
        if hasattr(js_obj, 'html'):
            python_result['html'] = str(js_obj.html)
        if hasattr(js_obj, 'css'):
            css_obj = js_obj.css
            if hasattr(css_obj, 'code'):
                python_result['css'] = {'code': str(css_obj.code)}
            else:
                python_result['css'] = {'code': str(css_obj)}
        if hasattr(js_obj, 'head'):
            python_result['head'] = str(js_obj.head)
        if hasattr(js_obj, 'error'):
            python_result['error'] = str(js_obj.error)
        if hasattr(js_obj, 'stack'):
            python_result['stack'] = str(js_obj.stack)
            
        return python_result
    except Exception as e:
        print(f"Error converting JSObject: {e}")
        # Fallback to string representation
        return {
            'html': str(js_obj),
            'css': {'code': ''}
        }


def extract_errors_from_context(ctx) -> List[str]:
    """
    Extract any errors from V8 context
    
    Args:
        ctx: STPyV8 context
        
    Returns:
        List of error messages
    """
    errors = []
    try:
        js_errors = ctx.eval("globalThis.__errors || []")
        if js_errors:
            for i in range(len(js_errors)):
                error = ctx.eval(f"globalThis.__errors[{i}]")
                errors.append(str(error))
            # Clear errors after extracting
            ctx.eval("globalThis.__errors = []")
    except:
        pass  # Silently ignore if we can't get errors
    
    return errors


def print_js_errors(ctx):
    """
    Print any JavaScript errors from V8 context
    
    Args:
        ctx: STPyV8 context
    """
    errors = extract_errors_from_context(ctx)
    for error in errors:
        print(f"[JS Error] {error}")


def is_js_object(obj) -> bool:
    """
    Check if object is a STPyV8 JSObject
    
    Args:
        obj: Object to check
        
    Returns:
        True if it's a JSObject, False otherwise
    """
    return (hasattr(obj, '__dict__') or 
            str(type(obj)) == "<class '_STPyV8.JSObject'>")
