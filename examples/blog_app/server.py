#!/usr/bin/env python3
"""Entry point for the blog app."""
from pathlib import Path
from fymo import create_app

PROJECT_ROOT = Path(__file__).resolve().parent

app = create_app(PROJECT_ROOT)
