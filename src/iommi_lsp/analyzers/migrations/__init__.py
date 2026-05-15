"""Migration analyzer — dependency-tuple autocomplete for ``Migration.dependencies``."""

from .analyzer import MigrationsAnalyzer, discover_migrations

__all__ = ["MigrationsAnalyzer", "discover_migrations"]
