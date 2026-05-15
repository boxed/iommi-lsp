# Template filter completion after the ``|`` pipe inside ``{{ … }}``.
# The popup mixes Django's built-in filters (``upper``, ``length``, …)
# with custom ones registered via ``@register.filter`` in any
# ``templatetags/`` library that the current template ``{% load %}``s.
#
# Regenerate with: docs/screenshots/regenerate.sh docs/screenshots/tapes/template-filter.tape

Output "/tmp/_vhs-template-filter.gif"

Set Shell "bash"
Set FontSize 16
Set Width 1100
Set Height 360
Set Theme "Catppuccin Mocha"
Set TypingSpeed 1ms

Hide
Type "cd docs/screenshots/fixtures/demo_project && hx --config $PWD/.xdg/helix/config.toml template_filter.html"
Enter
Sleep 4s
Show

# Open a fresh line below the {% load %} declaration. The partial ``s``
# matches both built-ins (``safe``, ``slice``, ``slugify``, …) and the
# custom ``shout`` filter from ``myapp_extras`` — same popup, separate
# ``filter`` vs ``filter (custom)`` details.
Type `o<p>{{ name|s`
Sleep 2s

Screenshot "docs/screenshots/out/template-filter.png"
Sleep 100ms
