"""
Embedded asset management system inspired by Frizzante.
Provides utilities for bundling and managing static assets within the Python application.
"""

from .copy import copy_file, copy_directory, copy_template_with_substitution


__all__ = [
    'copy_file',
    'copy_directory',
    'copy_template_with_substitution'
]
