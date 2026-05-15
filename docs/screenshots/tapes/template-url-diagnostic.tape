# `django-unknown-url-name` diagnostic raised on `{% url 'noooo' %}` —
# same code as the Python-side `reverse('noooo')` warning, scanned out
# of the template source.
#
# Regenerate with: docs/screenshots/regenerate.sh docs/screenshots/tapes/template-url-diagnostic.tape

Output "/tmp/_vhs-template-url-diagnostic.gif"

Set Shell "bash"
Set FontSize 16
Set Width 1100
Set Height 360
Set Theme "Catppuccin Mocha"
Set TypingSpeed 1ms

Hide
Type "cd docs/screenshots/fixtures/demo_project && hx --config $PWD/.xdg/helix/config.toml template_url_diagnostic.html"
Enter
Sleep 4s
Show

# Land cursor on the offending line so the inline diagnostic appears.
Type ":4"
Enter
Sleep 2s

Screenshot "docs/screenshots/out/template-url-diagnostic.png"
Sleep 100ms
