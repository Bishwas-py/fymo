"""
Routing system for Fymo
"""

from pathlib import Path
from typing import Dict, Optional, List
import yaml
import re


class Router:
    """Handle routing for Fymo applications"""
    
    def __init__(self, routes_file: Optional[Path] = None):
        """
        Initialize router
        
        Args:
            routes_file: Path to routes configuration file
        """
        self.routes = {}
        self.resources = []
        
        if routes_file and routes_file.exists():
            self._load_routes_from_file(routes_file)
        else:
            # Default routes
            self._setup_default_routes()
    
    def _load_routes_from_file(self, routes_file: Path):
        """Load routes from a Python or YAML file"""
        if routes_file.suffix == '.py':
            self._load_python_routes(routes_file)
        elif routes_file.suffix in ['.yml', '.yaml']:
            self._load_yaml_routes(routes_file)
    
    def _load_python_routes(self, routes_file: Path):
        """Load routes from a Python file"""
        import importlib.util
        spec = importlib.util.spec_from_file_location("routes", routes_file)
        routes_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(routes_module)
        
        if hasattr(routes_module, 'routes'):
            self.routes = routes_module.routes
        if hasattr(routes_module, 'resources'):
            self.resources = routes_module.resources
            self._expand_resources()
    
    def _load_yaml_routes(self, routes_file: Path):
        """Load routes from a YAML file"""
        with open(routes_file, 'r') as f:
            config = yaml.safe_load(f)
        
        if 'root' in config:
            controller, action = config['root'].split('.')
            self.routes['/'] = {
                'controller': controller,
                'action': action,
                'template': f"{controller}/{action}.svelte"
            }
        
        if 'resources' in config:
            self.resources = config['resources']
            self._expand_resources()
        
        if 'routes' in config:
            for path, handler in config['routes'].items():
                if isinstance(handler, str):
                    controller, action = handler.split('.')
                    self.routes[path] = {
                        'controller': controller,
                        'action': action,
                        'template': f"{controller}/{action}.svelte"
                    }
                else:
                    self.routes[path] = handler
    
    def _setup_default_routes(self):
        """Setup default routes"""
        self.routes = {
            '/': {
                'controller': 'home',
                'action': 'index',
                'template': 'home/index.svelte'
            }
        }
    
    def _expand_resources(self):
        """Expand resource routes (RESTful routing)"""
        for resource in self.resources:
            # Index route
            self.routes[f'/{resource}'] = {
                'controller': resource,
                'action': 'index',
                'template': f'{resource}/index.svelte'
            }
            
            # Show route
            self.routes[f'/{resource}/:id'] = {
                'controller': resource,
                'action': 'show',
                'template': f'{resource}/show.svelte'
            }
            
            # Edit route
            self.routes[f'/{resource}/:id/edit'] = {
                'controller': resource,
                'action': 'edit',
                'template': f'{resource}/edit.svelte'
            }
            
            # New route
            self.routes[f'/{resource}/new'] = {
                'controller': resource,
                'action': 'new',
                'template': f'{resource}/new.svelte'
            }
    
    def match(self, path: str) -> Optional[Dict]:
        """
        Match a path to a route
        
        Args:
            path: The URL path to match
            
        Returns:
            Route information dict or None
        """
        # Normalize path
        if path != '/' and path.endswith('/'):
            path = path[:-1]
        
        # Direct match
        if path in self.routes:
            return self.routes[path]
        
        # Try pattern matching (for :id style params)
        for route_pattern, route_info in self.routes.items():
            if ':' in route_pattern:
                # Convert :param to regex
                pattern = re.escape(route_pattern)
                pattern = re.sub(r'\\:(\w+)', r'(?P<\1>[^/]+)', pattern)
                pattern = f'^{pattern}$'
                
                match = re.match(pattern, path)
                if match:
                    # Add params to route info
                    route_info_copy = route_info.copy()
                    route_info_copy['params'] = match.groupdict()
                    return route_info_copy
        
        # Try to match as a resource route
        parts = path.strip('/').split('/')
        if parts and parts[0] in self.resources:
            resource = parts[0]
            
            # Default to index if no other parts
            if len(parts) == 1:
                return {
                    'controller': resource,
                    'action': 'index',
                    'template': f'{resource}/index.svelte'
                }
        
        return None
    
    def add_route(self, path: str, controller: str, action: str, template: Optional[str] = None):
        """Add a route dynamically"""
        if not template:
            template = f"{controller}/{action}.svelte"
        
        self.routes[path] = {
            'controller': controller,
            'action': action,
            'template': template
        }
