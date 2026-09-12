"""NearLink ranging and sensing desktop application."""

__version__ = "1.0.0"
__all__ = ["main"]


def main():
    """Load the GUI only when the desktop application is started."""
    from .main_window import main as run

    return run()
