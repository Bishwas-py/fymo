"""
Custom exceptions for Fymo framework
"""

from typing import Optional, Dict, Any


class FymoError(Exception):
    """Base exception for Fymo framework"""
    
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class ConfigurationError(FymoError):
    """Raised when there's a configuration error"""
    pass


class TemplateError(FymoError):
    """Raised when there's a template-related error"""
    pass


class CompilationError(FymoError):
    """Raised when Svelte compilation fails"""
    pass


class RenderingError(FymoError):
    """Raised when SSR rendering fails"""
    pass


class AssetError(FymoError):
    """Raised when asset serving fails"""
    pass


class RouterError(FymoError):
    """Raised when routing fails"""
    pass


class ControllerError(FymoError):
    """Raised when controller loading fails"""
    pass
