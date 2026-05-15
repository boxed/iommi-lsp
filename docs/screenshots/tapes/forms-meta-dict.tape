# Meta.widgets / labels / help_texts / error_messages dict-key completion
# against the bound model.
#
# Regenerate with: docs/screenshots/regenerate.sh docs/screenshots/tapes/forms-meta-dict.tape

Output "/tmp/_vhs-forms-meta-dict.gif"

Set Shell "bash"
Set FontSize 16
Set Width 1100
Set Height 360
Set Theme "Catppuccin Mocha"
Set TypingSpeed 1ms

Hide
Type "cd docs/screenshots/fixtures/demo_project && hx --config $PWD/.xdg/helix/config.toml forms_meta_dict.py:10"
Enter
Sleep 3s
Show

# Delete the placeholder ``pass`` line, open an indented line above.
Type "xd"
Sleep 100ms
Type "O"
Sleep 200ms
Type "widgets = {'"
Sleep 2s

Screenshot "docs/screenshots/out/forms-meta-dict.png"
Sleep 100ms
