"""
FyMo CLI - Command Line Interface for FyMo framework.
Inspired by Frizzante's comprehensive CLI system.
"""

import sys
from pathlib import Path

# Add the parent directory to sys.path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from cli.commands import create_project, generate_component, dev_server, build_project
from cli.utils import spinner, confirm, input_prompt

__all__ = [
    'create_project',
    'generate_component', 
    'dev_server',
    'build_project',
    'spinner',
    'confirm',
    'input_prompt'
]
