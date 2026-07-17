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
@click.option('--no-auth', is_flag=True, default=False,
              help='Skip the default password auth scaffold (app/auth/, /signin page)')
def new(name, template, no_auth):
    """Create a new Fymo project.

    The default scaffold includes working password auth: app/auth/,
    app/remote/auth.py, and a signin page at /signin, ready after
    `fymo dev`. Use --no-auth for apps bringing their own identity.
    """
    from fymo.cli.commands.new import create_project
    create_project(name, template, auth=not no_auth)


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


@cli.group()
def generate():
    """Generate app-owned code into the current project."""
    pass


@generate.command(name="auth")
@click.option('--clerk', is_flag=True, default=False,
              help='Clerk JWT resolver; the app adds pyjwt[crypto] to its own dependencies')
@click.option('--skeleton', is_flag=True, default=False,
              help='Bare resolver stub returning None; build your own mechanism')
def generate_auth_cmd(clerk, skeleton):
    """Scaffold app-owned auth into app/auth/ (password login by default)."""
    if clerk and skeleton:
        raise click.UsageError("--clerk and --skeleton are mutually exclusive")
    from fymo.cli.commands.generate_auth import generate_auth
    variant = 'clerk' if clerk else 'skeleton' if skeleton else 'password'
    generate_auth(variant)


@cli.group()
def schema():
    """Schema tooling for the database objects fymo providers own."""
    pass


@schema.command(name="provider-tables")
@click.option("--json", "as_json", is_flag=True, default=False,
              help="Emit JSON ([{kind, name, provider}, ...]) instead of plain lines")
def provider_tables_cmd(as_json):
    """List every table/function/type the configured providers create.

    Feed the output to your schema diff tool's exclude list so it never
    proposes dropping the job queue's tables."""
    from fymo.cli.commands.schema import run_provider_tables
    run_provider_tables(as_json=as_json)


@cli.command(name="jobs-worker")
@click.option("--dev", is_flag=True, default=False,
              help="Run in dev mode (sets FYMO_DEV=1, enables .env loading)")
def jobs_worker_cmd(dev):
    """Run the configured job provider's worker loop (e.g. Procrastinate)."""
    from fymo.cli.commands.jobs_worker import run_jobs_worker
    run_jobs_worker(dev=dev)


@cli.command(name="jobs-status")
@click.option("--limit", "-n", default=10, type=click.IntRange(min=1),
              help="How many recent jobs to show")
@click.option("--dev", is_flag=True, default=False,
              help="Run in dev mode (sets FYMO_DEV=1, enables .env loading)")
def jobs_status_cmd(limit, dev):
    """Show job counts by status and the most recent jobs."""
    from fymo.cli.commands.jobs_status import run_jobs_status
    run_jobs_status(limit=limit, dev=dev)


def main():
    """Main entry point"""
    try:
        cli()
    except Exception as e:
        Color.print_error(f"Error: {e}")
        raise


if __name__ == "__main__":
    main()
