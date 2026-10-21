"""Deploy versioned Quarto websites to a git branch."""

from importlib.metadata import version

# Set at build time from _extensions/version-selector/VERSION (see pyproject.toml).
__version__ = version("quarto-version-selector")
