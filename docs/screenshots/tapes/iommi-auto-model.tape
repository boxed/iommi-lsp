# Django field bridging inside iommi's auto__ context. Inside an
# `auto__include=[...]` string literal, iommi_lsp suggests User's fields
# drawn from auto__model=User. Using the string-literal variant of the
# bridge (instead of `columns__‸`) keeps ty quiet — ty doesn't see the
# popup position as a name reference.
#
# Regenerate with: docs/screenshots/regenerate.sh docs/screenshots/tapes/iommi-auto-model.tape

Output "/tmp/_vhs-iommi-auto-model.gif"

Set Shell "bash"
Set FontSize 16
Set Width 1100
Set Height 360
Set Theme "Catppuccin Mocha"
Set TypingSpeed 1ms

Hide
Type "cd docs/screenshots/fixtures/demo_project && hx --config $PWD/.xdg/helix/config.toml iommi_auto_model.py"
Enter
Sleep 3s
Show

# `ge` jumps to last line of buffer (fixture has 2 import lines), then `o`
# opens a new line below. Type the partial that triggers field completion
# from auto__model=User.
Type "geoTable(auto__model=User, auto__include=['"
Sleep 2s

Screenshot "docs/screenshots/out/iommi-auto-model.png"
Sleep 100ms
