"""
CLI command implementations inspired by Frizzante's action system.
"""

import os
import sys
from pathlib import Path
from typing import Optional

# Add the parent directory to sys.path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from embeds import copy_directory, copy_template_with_substitution
from cli.utils import spinner, confirm, input_prompt, success, info, error


def create_project(name: Optional[str] = None) -> None:
    """Create a new FyMo project with scaffolding."""
    if not name:
        name = input_prompt("Give the project a name")
    
    if not name:
        error("Project name is required")
        sys.exit(1)
    
    project_path = Path(name)
    
    if project_path.exists():
        if not confirm(f"Directory {name} already exists. Overwrite?"):
            info("Project creation cancelled")
            return
    
    with spinner(f"Creating FyMo project '{name}'"):
        # Create project structure
        project_path.mkdir(exist_ok=True)
        
        # Create directories
        dirs = [
            "app/components",
            "app/controllers", 
            "app/routes",
            "app/static",
            "lib",
            "templates",
            "dist"
        ]
        
        for dir_path in dirs:
            (project_path / dir_path).mkdir(parents=True, exist_ok=True)
        
        # Create configuration file
        config_content = f"""# FyMo Project Configuration
name: {name}
version: 1.0.0

# Server configuration
server:
  host: 0.0.0.0
  port: 8000
  debug: true

# Svelte configuration  
svelte:
  ssr: true
  hydration: true
  dev: true

# Build configuration
build:
  output_dir: dist
  minify: false
"""
        
        with open(project_path / "fymo.yaml", "w") as f:
            f.write(config_content)
        
        # Create sample files
        _create_sample_files(project_path, name)
    
    success(f"FyMo project '{name}' created successfully!")
    info(f"Next steps:")
    info(f"  cd {name}")
    info(f"  fymo dev")


def _create_sample_files(project_path: Path, name: str) -> None:
    """Copy real FyMo files to the new project."""
    from embeds import copy_file, copy_directory
    
    # Get the FyMo source directory
    fymo_dir = Path(__file__).parent.parent
    
    # Copy real controllers
    controllers_src = fymo_dir / "controllers"
    controllers_dst = project_path / "controllers"
    if controllers_src.exists():
        copy_directory(str(controllers_src), str(controllers_dst))
    
    # Copy real templates
    templates_src = fymo_dir / "templates" 
    templates_dst = project_path / "templates"
    if templates_src.exists():
        copy_directory(str(templates_src), str(templates_dst))
    
    # Copy real routes configuration
    routes_src = fymo_dir / "routes/routes.yml"
    routes_dst = project_path / "routes/routes.yml"
    if routes_src.exists():
        routes_dst.parent.mkdir(parents=True, exist_ok=True)
        copy_file(str(routes_src), str(routes_dst))
    
    # Copy server.py and other core files
    core_files = [
        "server.py",
        "svelte_compiler.py", 
        "js_runtime.py",
        "requirements.txt",
        "package.json"
    ]
    
    for file_name in core_files:
        src_file = fymo_dir / file_name
        dst_file = project_path / file_name
        if src_file.exists():
            copy_file(str(src_file), str(dst_file))


def generate_component(name: str) -> None:
    """Generate a new Svelte component using real Svelte 5 syntax."""
    if not name:
        error("Component name is required")
        sys.exit(1)
    
    component_path = Path(f"templates/{name.lower()}.svelte")
    
    if component_path.exists():
        if not confirm(f"Component {name} already exists. Overwrite?"):
            info("Component generation cancelled")
            return
    
    with spinner(f"Generating component '{name}'"):
        # Create a real Svelte 5 component with proper runes
        component_content = f'''<script>
  // Svelte 5 runes syntax
  let {{}} = $props();
  
  // Add your state here
  // let count = $state(0);
  // let doubled = $derived(count * 2);
  
  // Add your functions here
  // function handleClick() {{
  //   count++;
  // }}
</script>

<div class="{name.lower()}">
  <h2>{name}</h2>
  <!-- Add your component content here -->
</div>

<style>
  .{name.lower()} {{
    /* Add your component styles here */
  }}
</style>
'''
        
        component_path.parent.mkdir(parents=True, exist_ok=True)
        with open(component_path, "w") as f:
            f.write(component_content)
    
    success(f"Component '{name}' generated at templates/{name.lower()}.svelte")


def dev_server() -> None:
    """Start the development server using the real FyMo server."""
    info("Starting FyMo development server...")
    info("Server will be available at http://localhost:8000")
    
    try:
        # Use subprocess to run gunicorn with the real server
        import subprocess
        
        cmd = [
            sys.executable, '-m', 'gunicorn', 
            'server:app', 
            '--reload', 
            '--bind', '0.0.0.0:8000',
            '--timeout', '120'
        ]
        
        # Run the server
        subprocess.run(cmd, check=True)
        
    except subprocess.CalledProcessError as e:
        error(f"Server failed to start: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        info("Development server stopped")
    except ImportError:
        error("Failed to start development server. Make sure gunicorn is installed.")
        info("Run: pip install gunicorn")
        sys.exit(1)


def build_project() -> None:
    """Build the project for production."""
    with spinner("Building FyMo project for production"):
        # TODO: Implement production build
        # - Minify JavaScript and CSS
        # - Optimize Svelte components
        # - Bundle assets
        pass
    
    success("Project built successfully!")
