"""
Fymo - Production-ready Python SSR Framework for Svelte 5

A modern web framework that brings the power of Svelte 5 to Python backends,
enabling server-side rendering with full client-side hydration.
"""

from fymo.core.server import create_app, FymoApp
from fymo.core.compiler import SvelteCompiler
from fymo.core.runtime import JSRuntime

__version__ = "0.1.0"
__author__ = "Fymo Contributors"
__license__ = "MIT"

__all__ = [
    "create_app",
    "FymoApp",
    "SvelteCompiler", 
    "JSRuntime",
    "__version__"
]
