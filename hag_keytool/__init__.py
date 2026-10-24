"""HAG Key tool: generate cryptographically secure random keys."""

from .core import FORMATS, generate_key

__all__ = ["FORMATS", "generate_key"]
__version__ = "0.1.0"
