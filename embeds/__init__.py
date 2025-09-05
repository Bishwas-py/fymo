"""
Embedded asset management system inspired by Frizzante.
Provides utilities for bundling and managing static assets within the Python application.
"""

from .copy import copy_file, copy_directory, copy_template_with_substitution
from .is_asset import is_file, is_directory
from .read import read_directory, read_file_in_chunks
from .zip import zip_file, zip_directory

__all__ = [
    'copy_file',
    'copy_directory',
    'copy_template_with_substitution',
    'is_file',
    'is_directory',
    'read_directory',
    'read_file_in_chunks',
    'zip_file',
    'zip_directory'
]
