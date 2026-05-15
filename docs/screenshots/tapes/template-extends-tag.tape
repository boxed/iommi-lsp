# {% extends '...' %} completion inside an HTML template. Same template
# index as the Python-side `'…/…'` heuristic, but no `/` is required —
# the tag itself is unambiguous.
#
# Regenerate with: docs/screenshots/regenerate.sh docs/screenshots/tapes/template-extends-tag.tape

Output "/tmp/_vhs-template-extends-tag.gif"

Set Shell "bash"
Set FontSize 16
Set Width 1100
Set Height 360
Set Theme "Catppuccin Mocha"
Set TypingSpeed 1ms

Hide
Type "cd docs/screenshots/fixtures/demo_project && hx --config $PWD/.xdg/helix/config.toml template_extends_tag.html"
Enter
Sleep 4s
Show

Type `i{% extends '`
Sleep 2s

Screenshot "docs/screenshots/out/template-extends-tag.png"
Sleep 100ms
