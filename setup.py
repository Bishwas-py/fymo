#!/usr/bin/env python3
"""
Setup script for FyMo Svelte SSR
Run this to install dependencies and test the setup
"""

import subprocess
import sys
import os
from pathlib import Path

def run_command(cmd, description):
    """Run a command and handle errors"""
    print(f"🔧 {description}...")
    try:
        if isinstance(cmd, str):
            result = subprocess.run(cmd, shell=True, check=True, capture_output=True, text=True)
        else:
            result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        print(f"✅ {description} completed")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ {description} failed: {e.stderr}")
        return False

def run_python_code(code, description):
    """Run Python code directly"""
    print(f"🔧 {description}...")
    try:
        result = subprocess.run([sys.executable, '-c', code], check=True, capture_output=True, text=True)
        print(f"✅ {description} completed")
        if result.stdout:
            print(result.stdout.strip())
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ {description} failed: {e.stderr}")
        if e.stdout:
            print(f"Output: {e.stdout}")
        return False

def main():
    print("🚀 Setting up FyMo with Svelte 5 SSR support")
    
    base_dir = Path(__file__).parent
    os.chdir(base_dir)
    
    # Install Node.js dependencies
    if not run_command("npm install", "Installing Node.js dependencies"):
        return False
    
    # Install Python dependencies
    if not run_command("pip install -r requirements.txt", "Installing Python dependencies"):
        return False
    
    # Test Svelte compiler
    test_script = """
from svelte_compiler import SvelteCompiler
compiler = SvelteCompiler()
result = compiler.compile_ssr('<h1>Test</h1>', 'test.svelte')
print('✅ Svelte compiler working:', result.get('success', False))
"""
    
    if not run_python_code(test_script, "Testing Svelte compiler"):
        return False
    
    # Test STPyV8 runtime
    test_runtime = """
from js_runtime import JSRuntime
runtime = JSRuntime()
result = runtime.render_component('function render() { return {html: "<p>Test</p>"}; }', {})
print('✅ STPyV8 runtime working:', 'html' in result)
print('Result keys:', list(result.keys()))
"""
    
    if not run_python_code(test_runtime, "Testing STPyV8 runtime"):
        return False
    
    print("\n🎉 FyMo Svelte 5 SSR with STPyV8 setup complete!")
    print("📝 To test, run: python -m gunicorn server:app --reload")
    print("🌐 Then visit: http://localhost:8000/posts/index")
    print("✨ Features: Svelte 5 runes, STPyV8 runtime, SSR with hydration")

if __name__ == "__main__":
    main()


