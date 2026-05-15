# {% block <name> %} name completion in a child template. The LSP reads
# the file's `{% extends '...' %}` line, opens the parent template, and
# offers the parent's block names (with one level of grandparent
# recursion when present).
#
# Regenerate with: docs/screenshots/regenerate.sh docs/screenshots/tapes/template-block-tag.tape

Output "/tmp/_vhs-template-block-tag.gif"

Set Shell "bash"
Set FontSize 16
Set Width 1100
Set Height 360
Set Theme "Catppuccin Mocha"
Set TypingSpeed 1ms

Hide
Type "cd docs/screenshots/fixtures/demo_project && hx --config $PWD/.xdg/helix/config.toml template_block_tag.html"
Enter
Sleep 4s
Show

# `o` opens a fresh line below the {% extends %} declaration.
Type `o{% block `
Sleep 2s

Screenshot "docs/screenshots/out/template-block-tag.png"
Sleep 100ms
