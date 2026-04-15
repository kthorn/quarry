"""Quarry Labeling UI.

Usage:
    python -m quarry.ui
    python -m quarry.ui --port 8080
"""

import click

from quarry.config import settings


@click.command()
@click.option("--host", default=None, help="Host to bind to (default: from config)")
@click.option(
    "--port", default=None, type=int, help="Port to bind to (default: from config)"
)
@click.option("--debug", is_flag=True, default=False, help="Enable debug mode")
def main(host: str | None, port: int | None, debug: bool):
    """Run the Quarry labeling UI."""
    from quarry.ui.app import create_app

    app = create_app()
    app.run(
        host=host or settings.ui_host,
        port=port or settings.ui_port,
        debug=debug or settings.ui_debug,
    )


if __name__ == "__main__":
    main()
