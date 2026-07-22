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


def _conflict_options(fn):
    """Shared conflict-mode flags for every generator."""
    fn = click.option('--force', is_flag=True, default=False,
                      help='Overwrite existing files instead of refusing')(fn)
    fn = click.option('--dry-run', is_flag=True, default=False,
                      help='List every path that would be written; write nothing')(fn)
    fn = click.option('--diff', is_flag=True, default=False,
                      help='Show a unified diff against existing files; write nothing')(fn)
    return fn


def _check_conflict_flags(force, dry_run, diff):
    if sum((force, dry_run, diff)) > 1:
        raise click.UsageError("--force, --dry-run, and --diff are mutually exclusive")


@generate.command(name="auth")
@click.option('--clerk', is_flag=True, default=False,
              help='Clerk JWT resolver; the app adds pyjwt[crypto] to its own dependencies')
@click.option('--skeleton', is_flag=True, default=False,
              help='Bare resolver stub returning None; build your own mechanism')
@_conflict_options
def generate_auth_cmd(clerk, skeleton, force, dry_run, diff):
    """Scaffold app-owned auth into app/auth/ (password login by default)."""
    if clerk and skeleton:
        raise click.UsageError("--clerk and --skeleton are mutually exclusive")
    _check_conflict_flags(force, dry_run, diff)
    from fymo.cli.commands.generate_auth import generate_auth
    variant = 'clerk' if clerk else 'skeleton' if skeleton else 'password'
    generate_auth(variant, force=force, dry_run=dry_run, diff=diff)


@generate.command(name="page")
@click.argument('name')
@_conflict_options
def generate_page_cmd(name, force, dry_run, diff):
    """Generate a routed page: controller, Svelte template, route entry."""
    _check_conflict_flags(force, dry_run, diff)
    from fymo.cli.commands.generators import generate_page
    generate_page(name, force=force, dry_run=dry_run, diff=diff)


@generate.command(name="remote")
@click.argument('name')
@_conflict_options
def generate_remote_cmd(name, force, dry_run, diff):
    """Generate a remote module in app/remote/ plus a fymo.testing test."""
    _check_conflict_flags(force, dry_run, diff)
    from fymo.cli.commands.generators import generate_remote
    generate_remote(name, force=force, dry_run=dry_run, diff=diff)


@generate.command(name="resource")
@click.argument('name')
@_conflict_options
def generate_resource_cmd(name, force, dry_run, diff):
    """Generate a page and a remote module together."""
    _check_conflict_flags(force, dry_run, diff)
    from fymo.cli.commands.generators import generate_resource
    generate_resource(name, force=force, dry_run=dry_run, diff=diff)


@generate.command(name="component")
@click.argument('name')
@_conflict_options
def generate_component_cmd(name, force, dry_run, diff):
    """Generate a Svelte component in app/components/ (PascalCase name)."""
    _check_conflict_flags(force, dry_run, diff)
    from fymo.cli.commands.generators import generate_component
    generate_component(name, force=force, dry_run=dry_run, diff=diff)


@generate.command(name="layout")
@click.argument('section')
@_conflict_options
def generate_layout_cmd(section, force, dry_run, diff):
    """Generate a section layout for an existing app/templates/<section>/."""
    _check_conflict_flags(force, dry_run, diff)
    from fymo.cli.commands.generators import generate_layout
    generate_layout(section, force=force, dry_run=dry_run, diff=diff)


@generate.command(name="broadcast")
@click.argument('name')
@_conflict_options
def generate_broadcast_cmd(name, force, dry_run, diff):
    """Generate a broadcast channel module plus its discovery test."""
    _check_conflict_flags(force, dry_run, diff)
    from fymo.cli.commands.generators import generate_broadcast
    generate_broadcast(name, force=force, dry_run=dry_run, diff=diff)


@cli.group()
def destroy():
    """Remove generated code, the safe inverse of `fymo generate`."""
    pass


def _destroy_options(fn):
    fn = click.option('--force', is_flag=True, default=False,
                      help='Delete files even when modified since generation')(fn)
    fn = click.option('--dry-run', is_flag=True, default=False,
                      help='Print what would be deleted; touch nothing')(fn)
    return fn


@destroy.command(name="page")
@click.argument('name')
@_destroy_options
def destroy_page_cmd(name, force, dry_run):
    """Delete a generated page and its route entry."""
    from fymo.cli.commands.destroy import destroy_page
    destroy_page(name, force=force, dry_run=dry_run)


@destroy.command(name="remote")
@click.argument('name')
@_destroy_options
def destroy_remote_cmd(name, force, dry_run):
    """Delete a generated remote module and its test."""
    from fymo.cli.commands.destroy import destroy_remote
    destroy_remote(name, force=force, dry_run=dry_run)


@destroy.command(name="resource")
@click.argument('name')
@_destroy_options
def destroy_resource_cmd(name, force, dry_run):
    """Delete a generated resource (page + remote) and its route entry."""
    from fymo.cli.commands.destroy import destroy_resource
    destroy_resource(name, force=force, dry_run=dry_run)


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
