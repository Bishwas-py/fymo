"""
File reading utilities for embedded assets.
Inspired by Frizzante's asset reading capabilities.
"""

import os
from pathlib import Path
from typing import List, Generator


def read_directory(directory_path: str) -> List[str]:
    """
    Read all files in a directory and return their paths.
    
    Args:
        directory_path: Path to the directory to read
        
    Returns:
        List of file paths in the directory
    """
    try:
        path = Path(directory_path)
        if not path.exists() or not path.is_dir():
            return []
        
        files = []
        for item in path.rglob('*'):
            if item.is_file():
                files.append(str(item))
        
        return files
    except Exception:
        return []


def read_file_in_chunks(file_path: str, chunk_size: int = 8192) -> Generator[bytes, None, None]:
    """
    Read a file in chunks for memory-efficient processing.
    
    Args:
        file_path: Path to the file to read
        chunk_size: Size of each chunk in bytes
        
    Yields:
        Chunks of file data as bytes
    """
    try:
        with open(file_path, 'rb') as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                yield chunk
    except Exception:
        return
