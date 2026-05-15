# iommi `fields__name__attr='path'` value validated against the bound
# auto__model — typo in the path lights up `iommi-unknown-attr-path`.
#
# Regenerate with: docs/screenshots/regenerate.sh docs/screenshots/tapes/iommi-attr-bridge.tape

Output "/tmp/_vhs-iommi-attr-bridge.gif"

Set Shell "bash"
Set FontSize 16
Set Width 1100
Set Height 360
Set Theme "Catppuccin Mocha"
Set TypingSpeed 1ms

Hide
Type "cd docs/screenshots/fixtures/demo_project && hx --config $PWD/.xdg/helix/config.toml iommi_attr_bridge.py:5"
Enter
Sleep 3s
Show

# Open new line below the imports and type a Form(...) call with a typo
# in the attr value. `gh` returns the cursor to column 0 so the inline
# diagnostic isn't covered by a cursor selection.
Type "oForm(auto__model=User, fields__nickname__attr='usernme')"
Escape
Type "gh"
Sleep 2s

Screenshot "docs/screenshots/out/iommi-attr-bridge.png"
Sleep 100ms
