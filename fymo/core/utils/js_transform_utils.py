"""
JavaScript code transformation utilities for Svelte components
"""

import re
from typing import Tuple, Optional


def extract_filename_from_component(code: str) -> Tuple[str, str, str]:
    """
    Extract component name and filename from FILENAME assignment
    
    Args:
        code: JavaScript code containing FILENAME assignment
        
    Returns:
        Tuple of (component_name, filename, cleaned_code)
    """
    # Look for pattern: ComponentName[$.FILENAME] = 'path/to/file.svelte';
    filename_match = re.search(r'^(.+?)\[\\?\$\.FILENAME\]\s*=\s*[\'"]([^\'"]+)[\'"];?\n?', code, re.MULTILINE)
    
    if filename_match:
        component_name = filename_match.group(1).strip()
        filename = filename_match.group(2)
        cleaned_code = code.replace(filename_match.group(0), '')
        return component_name, filename, cleaned_code
    
    return '', '', code


def remove_es_module_imports(code: str) -> str:
    """
    Remove ES module import statements from Svelte compiled code
    
    Args:
        code: JavaScript code with import statements
        
    Returns:
        Code with import statements removed
    """
    # Remove various import patterns
    patterns = [
        r"import \* as \$ from ['\"]svelte/internal/server['\"];?",
        r"import \* as \$ from ['\"]svelte/internal/client['\"];?",
        r"import ['\"]svelte/internal/disclose-version['\"];?",
    ]
    
    cleaned_code = code
    for pattern in patterns:
        cleaned_code = re.sub(pattern, '', cleaned_code, flags=re.MULTILINE)
    
    return cleaned_code


def extract_component_function_name(code: str) -> Optional[str]:
    """
    Extract component function name from function declaration
    
    Args:
        code: JavaScript code containing function declaration
        
    Returns:
        Function name if found, None otherwise
    """
    function_match = re.search(r'function\s+(\w+)\s*\(', code)
    if function_match:
        return function_match.group(1)
    
    # Also try export default function pattern
    export_match = re.search(r'export default function\s+(\w+)', code)
    if export_match:
        return export_match.group(1)
    
    return None


def remove_export_default(code: str) -> str:
    """
    Remove export default statement from code
    
    Args:
        code: JavaScript code with export default
        
    Returns:
        Code with export default removed
    """
    return re.sub(r'export default \w+;?', '', code)




def transform_export_for_hydration(code: str) -> str:
    """
    Transform export default function for hydration use
    
    Args:
        code: JavaScript code with export default function
        
    Returns:
        Code with export transformed to const assignment
    """
    # Transform: export default function ComponentName -> const ComponentExport = function ComponentName
    return re.sub(
        r'export default function (\w+)', 
        r'const ComponentExport = function \1', 
        code
    )


def extract_component_name_from_export(code: str) -> Optional[str]:
    """
    Extract component name from transformed export
    
    Args:
        code: JavaScript code with ComponentExport pattern
        
    Returns:
        Component name if found, None otherwise
    """
    match = re.search(r'const ComponentExport = function (\w+)', code)
    return match.group(1) if match else None
