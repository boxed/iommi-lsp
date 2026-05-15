"""URL-name analyzer — completion + diagnostics for ``reverse('name')`` and
``{% url 'name' %}`` style references against a workspace ``urls.py`` index."""

from .analyzer import UrlAnalyzer, build_url_index, discover_urls

__all__ = ["UrlAnalyzer", "build_url_index", "discover_urls"]
