"""
Utility modules for Fymo framework
"""

from .js_transform_utils import (
    extract_filename_from_component,
    remove_es_module_imports,
)

from .json_utils import (
    safe_json_dumps,
    escape_js_for_embedding,
    prepare_props_json
)

from .v8_context_utils import (
    setup_console_mock,
    setup_browser_globals_mock,
    convert_js_object_to_dict,
    extract_errors_from_context,
    print_js_errors,
    is_js_object
)

from .runtime_templates import (
    get_commonjs_setup,
    get_server_runtime_wrapper,
    get_hydration_template,
    get_error_fallback_html
)

from .path_utils import (
    get_server_runtime_path,
    load_file_content,
    extract_component_name_from_path
)

from .error_utils import (
    format_ssr_error,
    print_ssr_error,
    create_error_response,
    create_js_error_response
)

__all__ = [
    # JS Transform Utils
    'extract_filename_from_component',
    'remove_es_module_imports', 
    
    # JSON Utils
    'safe_json_dumps',
    'escape_js_for_embedding',
    'prepare_props_json',
    
    # V8 Context Utils
    'setup_console_mock',
    'setup_browser_globals_mock',
    'convert_js_object_to_dict',
    'extract_errors_from_context',
    'print_js_errors',
    'is_js_object',
    
    # Runtime Templates
    'get_commonjs_setup',
    'get_server_runtime_wrapper',
    'get_hydration_template',
    'get_error_fallback_html',
    
    # Path Utils
    'get_server_runtime_path',
    'load_file_content',
    'extract_component_name_from_path',
    
    # Error Utils
    'format_ssr_error',
    'print_ssr_error',
    'create_error_response',
    'create_js_error_response'
]
