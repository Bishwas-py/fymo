"""
Error handling utilities for SSR and runtime operations
"""

import traceback
from typing import Dict, Any, Optional


def format_ssr_error(error: Exception, stack: Optional[str] = None) -> Dict[str, Any]:
    """
    Format SSR error for response
    
    Args:
        error: The exception that occurred
        stack: Optional stack trace string
        
    Returns:
        Formatted error dictionary
    """
    error_msg = str(error)
    stack_trace = stack or traceback.format_exc()
    
    return {
        'error': f"Unexpected error: {error_msg}",
        'html': f'<div class="ssr-error">SSR Error: {error_msg}</div>',
        'stack': stack_trace
    }


def print_ssr_error(error_msg: str, stack: Optional[str] = None):
    """
    Print SSR error with formatting
    
    Args:
        error_msg: Error message to print
        stack: Optional stack trace
    """
    print(f"\n=== SSR Error ===")
    print(f"Unexpected error in SSR: {error_msg}")
    
    if stack:
        print(f"Stack trace:\n{stack}")
    
    print("=== End SSR Error ===\n")


def create_error_response(error_msg: str, stack: Optional[str] = None) -> Dict[str, Any]:
    """
    Create standardized error response
    
    Args:
        error_msg: Error message
        stack: Optional stack trace
        
    Returns:
        Standardized error response dictionary
    """
    response = {
        'error': error_msg,
        'html': f'<div class="ssr-error">SSR Error: {error_msg}</div>'
    }
    
    if stack:
        response['stack'] = stack
    
    return response


def create_js_error_response(error_msg: str) -> Dict[str, Any]:
    """
    Create error response for JavaScript/V8 errors
    
    Args:
        error_msg: JavaScript error message
        
    Returns:
        Error response dictionary
    """
    return {
        'error': f"STPyV8 Runtime Error: {error_msg}",
        'html': f'<div class="ssr-error">SSR Error: {error_msg}</div>'
    }


def handle_component_error(error: Exception, component_name: str = "Unknown") -> Dict[str, Any]:
    """
    Handle component-specific errors
    
    Args:
        error: The exception that occurred
        component_name: Name of the component that failed
        
    Returns:
        Component error response
    """
    error_msg = f"Component '{component_name}' failed to render: {str(error)}"
    
    return {
        'error': error_msg,
        'html': f'<div class="ssr-error">{error_msg}</div>',
        'stack': traceback.format_exc()
    }


def is_critical_error(error: Exception) -> bool:
    """
    Determine if an error is critical and should stop execution
    
    Args:
        error: The exception to check
        
    Returns:
        True if error is critical, False otherwise
    """
    critical_errors = (
        ImportError,
        ModuleNotFoundError,
        SyntaxError,
        RuntimeError
    )
    
    return isinstance(error, critical_errors)


def get_error_context(error: Exception) -> Dict[str, Any]:
    """
    Get additional context information about an error
    
    Args:
        error: The exception to analyze
        
    Returns:
        Dictionary with error context
    """
    return {
        'type': type(error).__name__,
        'message': str(error),
        'critical': is_critical_error(error),
        'traceback': traceback.format_exc()
    }
