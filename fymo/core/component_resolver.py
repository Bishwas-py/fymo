"""
Component resolver for handling Svelte component imports
"""

import re
from pathlib import Path
from typing import Dict, Set, Optional, Tuple, List
from fymo.core.exceptions import TemplateError
from fymo.core.bundler import NPMBundler


class ComponentResolver:
    """Resolves and manages Svelte component imports"""
    
    def __init__(self, project_root: Path):
        """
        Initialize component resolver
        
        Args:
            project_root: Root directory of the project
        """
        self.project_root = project_root
        self.templates_root = project_root / "app" / "templates"
        self.component_cache: Dict[str, str] = {}
        self.dependency_graph: Dict[str, Set[str]] = {}
        self.bundler = NPMBundler(project_root)
    
    def resolve_imports(self, svelte_source: str, current_file_path: Path, target: str = 'browser') -> Tuple[str, Dict[str, str], Dict[str, str]]:
        """
        Resolve all component imports in a Svelte file
        
        Args:
            svelte_source: The Svelte component source code
            current_file_path: Path to the current component file
            target: Target environment ('browser' or 'node')
            
        Returns:
            Tuple of (processed_source, imported_components_dict, bundled_packages_dict)
        """
        imported_components = {}
        processed_source = svelte_source
        
        # Handle NPM package imports first
        processed_source, bundled_packages = self.bundler.bundle_npm_packages(processed_source, target)
        
        if bundled_packages:
            print(f"✅ Bundled NPM packages: {list(bundled_packages.keys())}")
        
        # Find all import statements for .svelte files
        svelte_import_pattern = r"import\s+(\w+)\s+from\s+['\"]([^'\"]+\.svelte)['\"];?"
        svelte_imports = re.findall(svelte_import_pattern, processed_source)
        
        for component_name, import_path in svelte_imports:
            # Resolve the import path relative to current file
            resolved_path = self._resolve_import_path(import_path, current_file_path)
            
            if not resolved_path.exists():
                raise TemplateError(f"Component not found: {import_path} (resolved to {resolved_path})")
            
            # Load the imported component
            component_source = self._load_component(resolved_path)
            
            # Recursively resolve imports in the imported component
            component_source, nested_imports, nested_packages = self.resolve_imports(component_source, resolved_path, target)
            
            # Add to imported components
            imported_components[component_name] = component_source
            imported_components.update(nested_imports)
            
            # Merge nested packages
            bundled_packages.update(nested_packages)
            
            # Track dependency
            self._track_dependency(str(current_file_path), str(resolved_path))
        
        # Remove svelte import statements from the source
        processed_source = re.sub(svelte_import_pattern, '', processed_source)
        
        return processed_source, imported_components, bundled_packages
    
    def _resolve_import_path(self, import_path: str, current_file_path: Path) -> Path:
        """
        Resolve import path relative to current file
        
        Args:
            import_path: The import path from the import statement
            current_file_path: Path to the current component file
            
        Returns:
            Resolved absolute path
        """
        if import_path.startswith('./'):
            # Relative to current file
            return current_file_path.parent / import_path[2:]
        elif import_path.startswith('../'):
            # Relative to parent directory
            return current_file_path.parent / import_path
        elif import_path.startswith('/'):
            # Absolute from templates root
            return self.templates_root / import_path[1:]
        else:
            # Relative to current file (no ./ prefix)
            return current_file_path.parent / import_path
    
    def _load_component(self, component_path: Path) -> str:
        """
        Load component source from file with caching
        
        Args:
            component_path: Path to the component file
            
        Returns:
            Component source code
        """
        path_str = str(component_path)
        
        if path_str in self.component_cache:
            return self.component_cache[path_str]
        
        try:
            with open(component_path, 'r', encoding='utf-8') as f:
                source = f.read()
            
            self.component_cache[path_str] = source
            return source
            
        except IOError as e:
            raise TemplateError(f"Could not read component {component_path}: {str(e)}")
    
    def _track_dependency(self, parent_file: str, dependency_file: str) -> None:
        """
        Track dependency relationship between components
        
        Args:
            parent_file: The file that imports the dependency
            dependency_file: The file being imported
        """
        if parent_file not in self.dependency_graph:
            self.dependency_graph[parent_file] = set()
        
        self.dependency_graph[parent_file].add(dependency_file)
    
    def get_dependencies(self, file_path: str) -> Set[str]:
        """
        Get all dependencies for a given file
        
        Args:
            file_path: Path to the file
            
        Returns:
            Set of dependency file paths
        """
        return self.dependency_graph.get(file_path, set())
    
    def clear_cache(self) -> None:
        """Clear the component cache"""
        self.component_cache.clear()
        self.dependency_graph.clear()
    
    def invalidate_cache_for_file(self, file_path: str) -> None:
        """
        Invalidate cache for a specific file and its dependents
        
        Args:
            file_path: Path to the file to invalidate
        """
        if file_path in self.component_cache:
            del self.component_cache[file_path]
        
        # Also invalidate any files that depend on this one
        for parent, deps in self.dependency_graph.items():
            if file_path in deps and parent in self.component_cache:
                del self.component_cache[parent]
