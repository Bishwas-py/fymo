"""
Path and file operation utilities
"""

import os
from pathlib import Path
from typing import Optional


def get_server_runtime_path() -> str:
    """
    Get the path to the bundled server runtime
    
    Returns:
        Absolute path to the server runtime file
    """
    # Get the path relative to this file
    current_dir = os.path.dirname(os.path.abspath(__file__))
    # Go up to fymo root, then to bundler
    fymo_root = os.path.dirname(os.path.dirname(current_dir))
    return os.path.join(fymo_root, 'bundler', 'js', 'dist', 'svelte-server-runtime.js')


def load_file_content(file_path: str) -> Optional[str]:
    """
    Load content from a file with error handling
    
    Args:
        file_path: Path to the file to load
        
    Returns:
        File content as string, or None if failed
    """
    try:
        if os.path.exists(file_path):
            with open(file_path, 'r', encoding='utf-8') as f:
                return f.read()
    except Exception as e:
        print(f"Failed to load file {file_path}: {e}")
    
    return None


def extract_component_name_from_path(template_path: str) -> str:
    """
    Extract component name from file path
    
    Args:
        template_path: Path to the template file
        
    Returns:
        Component name (capitalized stem of filename)
    """
    if not template_path:
        return 'Component'
    
    path = Path(template_path)
    return path.stem.capitalize()


def get_client_runtime_path() -> str:
    """
    Get the path to the client runtime bundle
    
    Returns:
        Absolute path to the client runtime file
    """
    current_dir = os.path.dirname(os.path.abspath(__file__))
    fymo_root = os.path.dirname(os.path.dirname(current_dir))
    return os.path.join(fymo_root, 'bundler', 'js', 'dist', 'svelte-runtime.js')


def ensure_directory_exists(directory_path: str) -> bool:
    """
    Ensure a directory exists, create if it doesn't
    
    Args:
        directory_path: Path to the directory
        
    Returns:
        True if directory exists or was created successfully
    """
    try:
        os.makedirs(directory_path, exist_ok=True)
        return True
    except Exception as e:
        print(f"Failed to create directory {directory_path}: {e}")
        return False


def get_relative_path(file_path: str, base_path: str) -> str:
    """
    Get relative path from base to file
    
    Args:
        file_path: Target file path
        base_path: Base directory path
        
    Returns:
        Relative path string
    """
    try:
        return os.path.relpath(file_path, base_path)
    except ValueError:
        # Paths are on different drives (Windows)
        return file_path


def file_exists(file_path: str) -> bool:
    """
    Check if a file exists
    
    Args:
        file_path: Path to check
        
    Returns:
        True if file exists, False otherwise
    """
    return os.path.isfile(file_path)
