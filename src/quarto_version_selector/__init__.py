"""Deploy versioned Quarto websites to a git branch, mike-style."""

from importlib.resources import files

__version__ = files(__package__).joinpath("VERSION").read_text().strip()
