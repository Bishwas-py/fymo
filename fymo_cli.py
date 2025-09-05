#!/usr/bin/env python3
"""
FyMo CLI Entry Point
Usage: python fymo_cli.py [command] [args]
"""

import sys
from pathlib import Path

# Add the current directory to sys.path for imports
sys.path.insert(0, str(Path(__file__).parent))

if __name__ == '__main__':
    from cli.main import main
    main()
