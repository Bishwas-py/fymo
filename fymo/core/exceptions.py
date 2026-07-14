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


class RouterError(FymoError):
    """Raised when routing fails"""
    pass
