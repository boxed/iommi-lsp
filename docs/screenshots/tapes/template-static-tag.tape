# {% static '<file>' %} completion. Same staticfiles index as the Python
# `static('foo.css')` call form — but here in template-tag form.
#
# Regenerate with: docs/screenshots/regenerate.sh docs/screenshots/tapes/template-static-tag.tape

Output "/tmp/_vhs-template-static-tag.gif"

Set Shell "bash"
Set FontSize 16
Set Width 1100
Set Height 360
Set Theme "Catppuccin Mocha"
Set TypingSpeed 1ms

Hide
Type "cd docs/screenshots/fixtures/demo_project && hx --config $PWD/.xdg/helix/config.toml template_static_tag.html"
Enter
Sleep 4s
Show

Type `o<link rel="stylesheet" href="{% static '`
Sleep 2s

Screenshot "docs/screenshots/out/template-static-tag.png"
Sleep 100ms
