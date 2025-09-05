"""
Asset existence and type checking utilities.
Inspired by Frizzante's embeds/is.go
"""

from pathlib import Path


def is_file(path: str) -> bool:
    """Check if path exists and is a file."""
    try:
        path_obj = Path(path)
        return path_obj.exists() and path_obj.is_file()
    except (OSError, ValueError):
        return False


def is_directory(path: str) -> bool:
    """Check if path exists and is a directory."""
    try:
        path_obj = Path(path)
        return path_obj.exists() and path_obj.is_dir()
    except (OSError, ValueError):
        return False


def exists(path: str) -> bool:
    """Check if path exists (file or directory)."""
    try:
        return Path(path).exists()
    except (OSError, ValueError):
        return False


def get_file_size(path: str) -> int:
    """Get file size in bytes, returns 0 if file doesn't exist."""
    try:
        path_obj = Path(path)
        if path_obj.exists() and path_obj.is_file():
            return path_obj.stat().st_size
        return 0
    except (OSError, ValueError):
        return 0
