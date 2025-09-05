"""
Initialize Fymo in an existing project
"""

from pathlib import Path
from fymo.utils.colors import Color


def initialize_project():
    """Initialize Fymo in an existing project directory"""
    current_dir = Path.cwd()
    
    Color.print_info(f"Initializing Fymo in {current_dir}")
    
    # Check if already initialized
    if (current_dir / 'fymo.yml').exists():
        Color.print_warning("This directory already appears to be a Fymo project!")
        return
    
    # Create minimal fymo.yml
    fymo_yml = """# Fymo project configuration
name: my-app
version: 1.0.0

routes:
  root: home.index

server:
  host: 127.0.0.1
  port: 8000
  reload: true
"""
    (current_dir / 'fymo.yml').write_text(fymo_yml)
    
    # Create basic structure
    (current_dir / 'app' / 'controllers').mkdir(parents=True, exist_ok=True)
    (current_dir / 'app' / 'templates').mkdir(parents=True, exist_ok=True)
    (current_dir / 'config').mkdir(exist_ok=True)
    
    Color.print_success("Fymo initialized successfully!")
    Color.print_info("Next steps: Create your controllers and templates in the app/ directory")
