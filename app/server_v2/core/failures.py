from __future__ import annotations


class DependencyUnavailableError(RuntimeError):
    """A required infrastructure dependency is temporarily unavailable."""

    def __init__(self, dependency: str) -> None:
        self.dependency = dependency
        super().__init__(f"{dependency} is temporarily unavailable")


__all__ = ["DependencyUnavailableError"]
