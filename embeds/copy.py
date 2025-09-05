"""
File and directory copying utilities for embedded assets.
Inspired by Frizzante's embeds/copy.go
"""

import os
import shutil
from pathlib import Path
from typing import Dict, Any


def copy_file(from_path: str, to_path: str) -> None:
    """Copy a file from source to destination, creating directories as needed."""
    to_file = Path(to_path)
    
    # Create parent directories if they don't exist
    to_file.parent.mkdir(parents=True, exist_ok=True)
    
    # Remove destination if it exists
    if to_file.exists():
        to_file.unlink()
    
    # Copy the file
    shutil.copy2(from_path, to_path)


def copy_directory(from_dir: str, to_dir: str, ignore_patterns: list = None) -> None:
    """Copy entire directory tree from source to destination."""
    from_path = Path(from_dir)
    to_path = Path(to_dir)
    
    if not from_path.exists():
        raise FileNotFoundError(f"Source directory {from_dir} not found")
    
    # Remove destination if it exists
    if to_path.exists():
        shutil.rmtree(to_path)
    
    # Copy directory tree
    def ignore_func(dir_path, names):
        ignored = []
        if ignore_patterns:
            for name in names:
                for pattern in ignore_patterns:
                    if pattern in name:
                        ignored.append(name)
                        break
        return ignored
    
    shutil.copytree(from_dir, to_dir, ignore=ignore_func if ignore_patterns else None)


def copy_template_with_substitution(from_path: str, to_path: str, substitutions: Dict[str, Any]) -> None:
    """Copy a template file with variable substitutions."""
    with open(from_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Perform substitutions
    for key, value in substitutions.items():
        content = content.replace(f"{{{key}}}", str(value))
    
    # Ensure destination directory exists
    Path(to_path).parent.mkdir(parents=True, exist_ok=True)
    
    # Write substituted content
    with open(to_path, 'w', encoding='utf-8') as f:
        f.write(content)
