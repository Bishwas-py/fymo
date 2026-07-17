"""
Initialize Fymo in an existing project
"""

from pathlib import Path
from fymo.utils.colors import Color
from fymo.cli.commands._scaffold import render_fymo_yml


def initialize_project():
    """Initialize Fymo in an existing project directory"""
    current_dir = Path.cwd()
    
    Color.print_info(f"Initializing Fymo in {current_dir}")
    
    # Check if already initialized
    if (current_dir / 'fymo.yml').exists():
        Color.print_warning("This directory already appears to be a Fymo project!")
        return
    
    # Create fymo.yml -- same shape `fymo new` scaffolds, named after this
    # directory since `fymo init` has no separate project-name argument.
    fymo_yml = render_fymo_yml(current_dir.name)
    (current_dir / 'fymo.yml').write_text(fymo_yml)
    
    # Create basic structure
    (current_dir / 'app' / 'controllers').mkdir(parents=True, exist_ok=True)
    (current_dir / 'app' / 'templates').mkdir(parents=True, exist_ok=True)

    # app/support/: Python-only home for shared server-side utilities, same
    # rationale as `fymo new`'s scaffold (see fymo/cli/commands/new.py).
    (current_dir / 'app' / 'support').mkdir(parents=True, exist_ok=True)
    (current_dir / 'app' / 'support' / '__init__.py').write_text('"""Shared server-side utilities"""')

    Color.print_success("Fymo initialized successfully!")
    Color.print_info("Next steps: Create your controllers and templates in the app/ directory")
    Color.print_info("Need auth? Run `fymo generate auth` (unlike `fymo new`, init does not scaffold it)")
