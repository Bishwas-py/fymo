#!/usr/bin/env python3
"""
Ensures the Svelte runtime is built before starting the server
"""

import subprocess
import os
from pathlib import Path

def ensure_svelte_runtime():
    """Check if Svelte runtime exists, build it if not"""
    base_dir = Path(__file__).resolve().parent
    runtime_path = base_dir / 'dist' / 'svelte-runtime.js'
    
    if not runtime_path.exists():
        print("🔨 Svelte runtime not found. Building it now...")
        
        # Ensure dist directory exists
        dist_dir = base_dir / 'dist'
        dist_dir.mkdir(exist_ok=True)
        
        try:
            # Run the build script
            result = subprocess.run(
                ['node', 'build_runtime.js'],
                cwd=base_dir,
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
