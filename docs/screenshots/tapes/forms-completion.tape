# ModelForm Meta.fields completion against the bound model.
#
# Regenerate with: vhs docs/screenshots/tapes/forms-completion.tape

Output "/tmp/_vhs-forms-completion.gif"

Set Shell "bash"
Set FontSize 16
Set Width 1100
Set Height 360
Set Theme "Catppuccin Mocha"
Set TypingSpeed 1ms

Hide
Type "cd docs/screenshots/fixtures/demo_project && hx --config $PWD/.xdg/helix/config.toml forms_completion.py:9"
Enter
Sleep 3s
Show

# Delete the placeholder ``pass`` line, open an indented line above.
Type "xd"
Sleep 100ms
Type "O"
Sleep 200ms
Type "fields = ['"
Sleep 2s

Screenshot "docs/screenshots/out/forms-completion.png"
Sleep 100ms
