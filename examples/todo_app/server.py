#!/usr/bin/env python3
"""Entry point for Fymo application"""

from pathlib import Path
from fymo import create_app

# Get project root
PROJECT_ROOT = Path(__file__).resolve().parent

# Create the WSGI application
app = create_app(PROJECT_ROOT)
