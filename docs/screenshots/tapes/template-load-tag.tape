# {% load <library> %} completion. Walks the workspace for any
# `templatetags/` package, exposes each `.py` module as a {% load %}
# candidate.
#
# Regenerate with: docs/screenshots/regenerate.sh docs/screenshots/tapes/template-load-tag.tape

Output "/tmp/_vhs-template-load-tag.gif"

Set Shell "bash"
Set FontSize 16
Set Width 1100
Set Height 360
Set Theme "Catppuccin Mocha"
Set TypingSpeed 1ms

Hide
Type "cd docs/screenshots/fixtures/demo_project && hx --config $PWD/.xdg/helix/config.toml template_load_tag.html"
Enter
Sleep 4s
Show

Type `i{% load `
Sleep 2s

Screenshot "docs/screenshots/out/template-load-tag.png"
Sleep 100ms
