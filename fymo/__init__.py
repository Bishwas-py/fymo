"""
Fymo - Production-ready Python SSR Framework for Svelte 5

A modern web framework that brings the power of Svelte 5 to Python backends,
enabling server-side rendering with full client-side hydration.
"""

from importlib.metadata import PackageNotFoundError, version

from fymo.core.server import create_app, FymoApp

# Single source of truth is pyproject.toml, read from the installed
# distribution's metadata (issue #47: a second hardcoded copy here sat at
# 0.1.0 while releases marched on). The fallback only triggers when fymo is
# imported without being installed at all (e.g. a bare source checkout on
# sys.path), where no metadata exists to be right about.
try:
    __version__ = version("fymo")
except PackageNotFoundError:  # pragma: no cover
    __version__ = "0.0.0.dev0"
__author__ = "Fymo Contributors"
__license__ = "MIT"

__all__ = [
    "create_app",
    "FymoApp",
    "__version__"
]
