#!/usr/bin/env python3
"""
FyMo CLI - Main entry point
Inspired by Frizzante's comprehensive CLI system
"""

import sys
import argparse
from typing import List, Optional

from .commands import create_project, generate_component, dev_server, build_project
from .utils import error, info, success


def main(args: Optional[List[str]] = None) -> None:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        prog='fymo',
        description='FyMo - Full-stack Python web framework with Svelte 5 SSR',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  fymo new my-project        Create a new FyMo project
  fymo generate component Button   Generate a Svelte component
  fymo dev                   Start development server
  fymo build                 Build for production
        '''
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # New project command
    new_parser = subparsers.add_parser('new', help='Create a new FyMo project')
    new_parser.add_argument('name', nargs='?', help='Project name')
    
    # Generate command
    gen_parser = subparsers.add_parser('generate', aliases=['gen'], help='Generate components')
    gen_subparsers = gen_parser.add_subparsers(dest='generate_type')
    
    # Generate component
    comp_parser = gen_subparsers.add_parser('component', aliases=['comp'], help='Generate Svelte component')
    comp_parser.add_argument('name', help='Component name')
    
    # Dev server command
    subparsers.add_parser('dev', help='Start development server')
    
    # Build command
    subparsers.add_parser('build', help='Build for production')
    
    # Version command
    subparsers.add_parser('version', help='Show version information')
    
    # Parse arguments
    if args is None:
        args = sys.argv[1:]
    
    parsed_args = parser.parse_args(args)
    
    # Handle commands
    try:
        if parsed_args.command == 'new':
            create_project(parsed_args.name)
        
        elif parsed_args.command in ('generate', 'gen'):
            if parsed_args.generate_type in ('component', 'comp'):
                generate_component(parsed_args.name)
            else:
                error("Unknown generate type. Use 'component'")
                sys.exit(1)
        
        elif parsed_args.command == 'dev':
            dev_server()
        
        elif parsed_args.command == 'build':
            build_project()
        
        elif parsed_args.command == 'version':
            info("FyMo v1.0.0 - Svelte 5 SSR Framework")
        
        else:
            parser.print_help()
    
    except KeyboardInterrupt:
        info("\nOperation cancelled by user")
        sys.exit(1)
    except Exception as e:
        error(f"Command failed: {str(e)}")
        sys.exit(1)


if __name__ == '__main__':
    main()
