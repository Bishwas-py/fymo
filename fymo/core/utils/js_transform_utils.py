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
