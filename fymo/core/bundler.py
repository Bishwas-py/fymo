"""
NPM Package bundler for Fymo using esbuild
"""

import subprocess
import json
import tempfile
import os
import re
from pathlib import Path
from typing import Dict, Any, List, Set, Optional, Tuple

from fymo.core.exceptions import CompilationError


class NPMBundler:
    """Bundles NPM packages for use in Fymo components"""
    
    def __init__(self, project_root: Path):
        """
        Initialize NPM bundler
        
        Args:
            project_root: Root directory of the project
        """
        self.project_root = project_root
        self.bundle_cache: Dict[str, str] = {}
        
    def extract_npm_imports(self, source_code: str) -> List[Tuple[str, str]]:
        """
        Extract NPM package imports from source code
        
        Args:
            source_code: The source code to analyze
            
        Returns:
            List of (import_statement, package_name) tuples
        """
        # Match various import patterns for NPM packages
        patterns = [
            # import { format } from 'date-fns'
            r"import\s*\{([^}]+)\}\s*from\s*['\"]([^'\"./][^'\"]*)['\"];?",
            # import format from 'date-fns'
            r"import\s+(\w+)\s+from\s+['\"]([^'\"./][^'\"]*)['\"];?",
            # import * as dateFns from 'date-fns'
            r"import\s*\*\s*as\s+(\w+)\s+from\s+['\"]([^'\"./][^'\"]*)['\"];?",
            # import 'date-fns' (side effects)
            r"import\s+['\"]([^'\"./][^'\"]*)['\"];?"
        ]
        
        imports = []
        for pattern in patterns:
            matches = re.findall(pattern, source_code)
            for match in matches:
                if len(match) == 2:
                    import_name, package_name = match
                    full_import = re.search(pattern, source_code).group(0)
                    imports.append((full_import, package_name))
                else:
                    # Side effect import
                    package_name = match[0] if isinstance(match, tuple) else match
                    full_import = re.search(pattern, source_code).group(0)
                    imports.append((full_import, package_name))
        
        return imports
    
    def bundle_npm_packages(self, source_code: str, target: str = 'browser') -> Tuple[str, Dict[str, str]]:
        """
        Bundle NPM packages and return modified source code
        
        Args:
            source_code: Source code with NPM imports
            target: Target environment ('browser' or 'node')
            
        Returns:
            Tuple of (modified_source_code, bundled_packages_dict)
        """
        imports = self.extract_npm_imports(source_code)
        if not imports:
            return source_code, {}
        
        bundled_packages = {}
        modified_source = source_code
        
        # Get unique packages
        unique_packages = set()
        for _, package_name in imports:
            unique_packages.add(package_name)
        
        # Bundle each package
        for package_name in unique_packages:
            try:
                bundled_code = self._bundle_single_package(package_name, target)
                bundled_packages[package_name] = bundled_code
                
                # Replace imports with global variable access
                modified_source = self._replace_package_imports(modified_source, package_name)
                
            except Exception as e:
                print(f"Warning: Failed to bundle {package_name}: {e}")
                # Remove the import to prevent errors
                for import_statement, pkg in imports:
                    if pkg == package_name:
                        modified_source = modified_source.replace(import_statement, '')
        
        return modified_source, bundled_packages
    
    def _bundle_single_package(self, package_name: str, target: str) -> str:
        """
        Bundle a single NPM package using esbuild
        
        Args:
            package_name: Name of the package to bundle
            target: Target environment
            
        Returns:
            Bundled JavaScript code
        """
        cache_key = f"{package_name}_{target}"
        if cache_key in self.bundle_cache:
            return self.bundle_cache[cache_key]
        
        # Create temporary entry file in the project directory where node_modules exists
        with tempfile.NamedTemporaryFile(mode='w', suffix='.js', delete=False, dir=self.project_root) as f:
            # Create an entry point that exports the package
            f.write(f"""
import * as pkg from '{package_name}';
globalThis._fymo_packages = globalThis._fymo_packages || {{}};
globalThis._fymo_packages['{package_name}'] = pkg;
""")
            entry_file = f.name
        
        try:
            # Use esbuild to bundle - make sure we're in the right directory with node_modules
            result = subprocess.run([
                'npx', 'esbuild', entry_file,
                '--bundle',
                '--format=iife',
                '--platform=browser' if target == 'browser' else 'node',
                '--target=es2020',
                '--minify',
                '--external:fs',
                '--external:path',
                '--external:os'
            ], capture_output=True, text=True, cwd=self.project_root)
            
            if result.returncode == 0:
                bundled_code = result.stdout
                self.bundle_cache[cache_key] = bundled_code
                print(f"✅ Successfully bundled {package_name}")
                return bundled_code
            else:
                print(f"❌ esbuild failed for {package_name}: {result.stderr}")
                raise CompilationError(f"esbuild failed: {result.stderr}")
                
        finally:
            os.unlink(entry_file)
    
    def _replace_package_imports(self, source_code: str, package_name: str) -> str:
        """
        Replace package imports with global variable access
        
        Args:
            source_code: Source code with imports
            package_name: Package name to replace
            
        Returns:
            Modified source code
        """
        # Replace different import patterns
        patterns_replacements = [
            # import { format } from 'date-fns' -> const { format } = globalThis._fymo_packages['date-fns']
            (rf"import\s*\{{([^}}]+)\}}\s*from\s*['\"]({re.escape(package_name)})['\"];?",
             rf"const {{\1}} = globalThis._fymo_packages['{package_name}'];"),
            
            # import format from 'date-fns' -> const format = globalThis._fymo_packages['date-fns'].default
            (rf"import\s+(\w+)\s+from\s*['\"]({re.escape(package_name)})['\"];?",
             rf"const \1 = globalThis._fymo_packages['{package_name}'].default || globalThis._fymo_packages['{package_name}'];"),
            
            # import * as dateFns from 'date-fns' -> const dateFns = globalThis._fymo_packages['date-fns']
            (rf"import\s*\*\s*as\s+(\w+)\s+from\s*['\"]({re.escape(package_name)})['\"];?",
             rf"const \1 = globalThis._fymo_packages['{package_name}'];"),
            
            # import 'date-fns' -> (remove, side effects handled by bundle)
            (rf"import\s+['\"]({re.escape(package_name)})['\"];?", "")
        ]
        
        modified_source = source_code
        for pattern, replacement in patterns_replacements:
            modified_source = re.sub(pattern, replacement, modified_source)
        
        return modified_source
    
    def generate_bundle_loader(self, bundled_packages: Dict[str, str]) -> str:
        """
        Generate JavaScript code to load all bundled packages
        
        Args:
            bundled_packages: Dictionary of package_name -> bundled_code
            
        Returns:
            JavaScript code to load packages
        """
        if not bundled_packages:
            return ""
        
        loader_parts = [
            "// Load bundled NPM packages",
            "globalThis._fymo_packages = globalThis._fymo_packages || {};"
        ]
        
        for package_name, bundled_code in bundled_packages.items():
            loader_parts.append(f"// Bundle for {package_name}")
            loader_parts.append(f"(function() {{ {bundled_code} }})();")
        
        return "\n".join(loader_parts)
    
    def clear_cache(self) -> None:
        """Clear the bundle cache"""
        self.bundle_cache.clear()
