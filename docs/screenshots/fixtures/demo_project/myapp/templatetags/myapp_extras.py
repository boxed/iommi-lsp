"""Demo fixture: a templatetags library with a couple of custom filters
so the screenshot can show a mix of built-ins and library filters."""

from django import template

register = template.Library()


@register.filter
def shout(value):
    return value.upper()


@register.filter(name="excited")
def add_exclamation(value):
    return f"{value}!"
