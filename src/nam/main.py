"""Module entry point for ``python -m nam``."""

from .cli import app


def main() -> None:
    """Run the Typer CLI app."""
    app()


if __name__ == "__main__":
    main()
