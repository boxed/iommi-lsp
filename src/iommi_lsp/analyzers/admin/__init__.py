"""Admin analyzer — model-field-name completion + diagnostics inside
``ModelAdmin`` subclasses' ``list_display`` / ``list_filter`` / etc."""

from .analyzer import AdminAnalyzer

__all__ = ["AdminAnalyzer"]
