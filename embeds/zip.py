"""
ZIP utilities for embedded assets.
Inspired by Frizzante's asset compression capabilities.
"""

import zipfile
import os
from pathlib import Path
from typing import Optional


def zip_file(file_path: str, zip_path: str) -> bool:
    """
    Compress a single file into a ZIP archive.
    
    Args:
        file_path: Path to the file to compress
        zip_path: Path where the ZIP file should be created
        
    Returns:
        True if successful, False otherwise
    """
    try:
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            zipf.write(file_path, os.path.basename(file_path))
        return True
    except Exception:
        return False


def zip_directory(directory_path: str, zip_path: str, exclude_patterns: Optional[list] = None) -> bool:
    """
    Compress a directory into a ZIP archive.
    
    Args:
        directory_path: Path to the directory to compress
        zip_path: Path where the ZIP file should be created
        exclude_patterns: List of patterns to exclude from compression
        
    Returns:
        True if successful, False otherwise
    """
    try:
        exclude_patterns = exclude_patterns or []
        
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, dirs, files in os.walk(directory_path):
                for file in files:
                    file_path = os.path.join(root, file)
                    
                    # Check if file should be excluded
                    should_exclude = False
                    for pattern in exclude_patterns:
                        if pattern in file_path:
                            should_exclude = True
                            break
                    
                    if not should_exclude:
                        # Calculate relative path for the archive
                        arcname = os.path.relpath(file_path, directory_path)
                        zipf.write(file_path, arcname)
        
        return True
    except Exception:
        return False
