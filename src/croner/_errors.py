"""Exceptions raised by croner."""

__all__ = ["CronError"]


class CronError(ValueError):
    """Raised for invalid patterns, options or dates."""
