"""
JSON and JavaScript escaping utilities
"""

import json
from typing import Any, Dict


def safe_json_dumps(obj: Any, **kwargs) -> str:
    """
    Safely serialize object to JSON with proper escaping
    
    Args:
        obj: Object to serialize
        **kwargs: Additional arguments for json.dumps
        
    Returns:
        JSON string with safe defaults
    """
    defaults = {
        'ensure_ascii': False,
        'separators': (',', ':')
    }
    defaults.update(kwargs)
    
    return json.dumps(obj, **defaults)


def escape_js_for_embedding(js_code: str) -> str:
    """
    Escape JavaScript code for embedding in templates
    This is critical for proper hydration!
    
    Args:
        js_code: JavaScript code to escape
        
    Returns:
        Properly escaped JavaScript code
    """
    return json.dumps(js_code)


def prepare_props_json(props: Dict[str, Any]) -> str:
    """
    Prepare props for JSON serialization in templates
    
    Args:
        props: Props dictionary
        
    Returns:
        JSON string ready for embedding
    """
    if not props:
        return '{}'
    
    return safe_json_dumps(props)


def create_props_script_tag(props: Dict[str, Any], element_id: str = 'svelte-props') -> str:
    """
    Create a script tag containing props for hydration
    
    Args:
        props: Props to embed
        element_id: ID for the script element
        
    Returns:
        HTML script tag with props
    """
    props_json = prepare_props_json(props)
    return f'<script id="{element_id}" type="application/json">{props_json}</script>'


def escape_template_literal(content: str) -> str:
    """
    Escape content for use in JavaScript template literals
    
    Args:
        content: Content to escape
        
    Returns:
        Escaped content safe for template literals
    """
    return (content
            .replace('\\', '\\\\')  # Escape backslashes FIRST
            .replace('`', '\\`')    # Then escape backticks  
            .replace('${', '\\${')  # Finally escape interpolations
    )
