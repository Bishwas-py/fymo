#!/usr/bin/env python3
"""
Fymo CLI - Command line interface for Fymo framework
"""

import click
from pathlib import Path
from fymo.__version__ import __version__
from fymo.utils.colors import Color


@click.group()
@click.version_option(version=__version__, prog_name="fymo")
def cli():
    """Fymo - Production-ready Python SSR Framework for Svelte 5"""
    pass


@cli.command()
@click.argument('name')
@click.option('--template', '-t', default='default', help='Project template to use')
def new(name, template):
    """Create a new Fymo project"""
    from fymo.cli.commands.new import create_project
    create_project(name, template)


@cli.command()
@click.argument('type', type=click.Choice(['component', 'controller', 'model']))
@click.argument('name')
def generate(type, name):
    """Generate a new component, controller, or model"""
    from fymo.cli.commands.generate import generate_item
    generate_item(type, name)


@cli.command()
@click.option('--host', '-h', default='127.0.0.1', help='Host to bind to')
@click.option('--port', '-p', default=8000, type=int, help='Port to bind to')
@click.option('--reload', '-r', is_flag=True, default=True, help='Enable auto-reload')
def serve(host, port, reload):
    """Start the development server"""
    from fymo.cli.commands.serve import run_server
    run_server(host, port, reload)


@cli.command()
@click.option('--output', '-o', default='dist', help='Output directory')
@click.option('--minify', '-m', is_flag=True, help='Minify output')
def build(output, minify):
    """Build the project for production"""
    from fymo.cli.commands.build import build_project
    build_project(output, minify)


@cli.command()
def init():
    """Initialize Fymo in an existing project"""
    from fymo.cli.commands.init import initialize_project
    initialize_project()


@cli.command(name='build-runtime')
def build_runtime_cmd():
    """Build the Svelte runtime for the current project"""
    from fymo.cli.commands.build import build_runtime
    build_runtime()


def main():
    """Main entry point"""
    try:
        cli()
    except Exception as e:
        Color.print_error(f"Error: {e}")
        raise


if __name__ == "__main__":
    main()
