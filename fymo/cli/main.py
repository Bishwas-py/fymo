#!/usr/bin/env python3
"""
Fymo CLI - Command line interface for Fymo framework
"""

import click
from pathlib import Path
from fymo import __version__
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
@click.option('--host', '-h', default='127.0.0.1', help='Host to bind to')
@click.option('--port', '-p', default=8000, type=int, help='Port to bind to')
@click.option('--prod', is_flag=True, default=False, help='Serve via a production server instead of the dev server')
@click.option('--workers', '-w', default=4, type=int, help='Worker processes (--prod only)')
@click.option('--server', type=click.Choice(['auto', 'granian', 'gunicorn']), default='auto',
              help='Production server (--prod only); auto prefers granian when installed, else gunicorn')
def serve(host, port, prod, workers, server):
    """Alias for `fymo dev`, or production via --prod"""
    from fymo.cli.commands.serve import run_server
    run_server(host, port, prod=prod, workers=workers, server=server)


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


@cli.command(name="dev")
@click.option("--host", default="127.0.0.1")
@click.option("--port", default=8000, type=int)
def dev_cmd(host, port):
    """Start dev server with file watcher."""
    from fymo.cli.commands.dev import run_dev
    run_dev(host=host, port=port)


@cli.command(name="jobs-worker")
def jobs_worker_cmd():
    """Run the configured job provider's worker loop (e.g. Procrastinate)."""
    from fymo.cli.commands.jobs_worker import run_jobs_worker
    run_jobs_worker()


def main():
    """Main entry point"""
    try:
        cli()
    except Exception as e:
        Color.print_error(f"Error: {e}")
        raise


if __name__ == "__main__":
    main()
