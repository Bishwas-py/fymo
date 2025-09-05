"""
CLI utility functions inspired by Frizzante's TUI system.
"""

import sys
import time
import threading
from contextlib import contextmanager
from typing import Optional


class Colors:
    """Terminal color codes."""
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    MAGENTA = '\033[95m'
    CYAN = '\033[96m'
    WHITE = '\033[97m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'
    END = '\033[0m'


def success(message: str) -> None:
    """Print success message in green."""
    print(f"{Colors.GREEN}✅ {message}{Colors.END}")


def info(message: str) -> None:
    """Print info message in blue."""
    print(f"{Colors.BLUE}ℹ️  {message}{Colors.END}")


def warning(message: str) -> None:
    """Print warning message in yellow."""
    print(f"{Colors.YELLOW}⚠️  {message}{Colors.END}")


def error(message: str) -> None:
    """Print error message in red."""
    print(f"{Colors.RED}❌ {message}{Colors.END}")


def input_prompt(message: str) -> str:
    """Prompt user for input with styled message."""
    return input(f"{Colors.CYAN}? {message}: {Colors.END}")


def confirm(message: str, default: bool = True) -> bool:
    """Ask user for yes/no confirmation."""
    suffix = " [Y/n]" if default else " [y/N]"
    response = input(f"{Colors.YELLOW}? {message}{suffix}: {Colors.END}").lower().strip()
    
    if not response:
        return default
    
    return response in ('y', 'yes', 'true', '1')


class Spinner:
    """Simple terminal spinner."""
    
    def __init__(self, message: str):
        self.message = message
        self.spinning = False
        self.thread = None
        self.chars = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
        
    def _spin(self):
        """Spin animation loop."""
        i = 0
        while self.spinning:
            char = self.chars[i % len(self.chars)]
            sys.stdout.write(f"\r{Colors.CYAN}{char} {self.message}...{Colors.END}")
            sys.stdout.flush()
            time.sleep(0.1)
            i += 1
        
        # Clear the line
        sys.stdout.write(f"\r{' ' * (len(self.message) + 10)}\r")
        sys.stdout.flush()
    
    def start(self):
        """Start the spinner."""
        self.spinning = True
        self.thread = threading.Thread(target=self._spin)
        self.thread.daemon = True
        self.thread.start()
    
    def stop(self):
        """Stop the spinner."""
        self.spinning = False
        if self.thread:
            self.thread.join()


@contextmanager
def spinner(message: str):
    """Context manager for spinner."""
    spin = Spinner(message)
    spin.start()
    try:
        yield
    finally:
        spin.stop()
