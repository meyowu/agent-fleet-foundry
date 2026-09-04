"""Agent Fleet package."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("agent-fleet")
except PackageNotFoundError:  # pragma: no cover - editable installs normally provide metadata
    __version__ = "0.1.0"

__all__ = ["__version__"]
