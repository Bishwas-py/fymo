#!/usr/bin/env python3
"""
Ensures the Svelte runtime is built before starting the server
"""

import subprocess
import os
from pathlib import Path
from typing import Optional

def ensure_svelte_runtime(project_root: Optional[Path] = None):
    """Check if Svelte runtime exists, build it if not"""
    if project_root is None:
        project_root = Path.cwd()
    else:
        project_root = Path(project_root)
    
    runtime_path = project_root / 'dist' / 'svelte-runtime.js'
    
    if not runtime_path.exists():
        print("🔨 Svelte runtime not found. Building it now...")
        
        # Ensure dist directory exists
        dist_dir = project_root / 'dist'
        dist_dir.mkdir(exist_ok=True)
        
        # Find build script
        build_script = project_root / 'build_runtime.js'
        if not build_script.exists():
            # Try package location
            package_dir = Path(__file__).resolve().parent.parent.parent
            build_script = package_dir / 'build_runtime.js'
        
        try:
            # Run the build script
            result = subprocess.run(
                ['node', str(build_script)],
                cwd=project_root,
                capture_output=True,
                text=True
            )
            
            if result.returncode == 0:
                print("✅ Svelte runtime built successfully!")
                return True
            else:
                print(f"❌ Failed to build Svelte runtime: {result.stderr}")
                return False
                
        except FileNotFoundError:
            print("❌ Node.js not found. Please install Node.js to build the Svelte runtime.")
            return False
        except Exception as e:
            print(f"❌ Error building Svelte runtime: {e}")
            return False
    else:
        print("✅ Svelte runtime already exists")
        return True

if __name__ == "__main__":
    ensure_svelte_runtime()
