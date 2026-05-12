# Refinable autocomplete inside an iommi class call. `Table(c‸` suggests
# columns__, cell__, query__ — synthesised stubs cover Table even before
# the iommi graph builds.
#
# Regenerate with: docs/screenshots/regenerate.sh docs/screenshots/tapes/iommi-refinable.tape

Output "/tmp/_vhs-iommi-refinable.gif"

Set Shell "bash"
Set FontSize 16
Set Width 1100
Set Height 360
Set Theme "Catppuccin Mocha"
Set TypingSpeed 1ms

Hide
Type "cd docs/screenshots/fixtures/demo_project && hx --config $PWD/.xdg/helix/config.toml iommi_refinable.py"
Enter
Sleep 3s
Show

# Deep chain through the iommi refinable graph: Table → columns (members
# of Column) → email (a Column, surfaced via auto__model=User) → cell
# (class_ref to Cell) → Cell's configurable surface.
# `ge` lands on line 2, `o` opens line 3 below the 2-line fixture.
Type "geoTable(auto__model=User, columns__email__cell__"
Sleep 2s

Screenshot "docs/screenshots/out/iommi-refinable.png"
Sleep 100ms
