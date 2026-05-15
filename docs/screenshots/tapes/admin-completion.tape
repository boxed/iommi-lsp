# Admin list_display completion inside a ModelAdmin subclass.
#
# Regenerate with: vhs docs/screenshots/tapes/admin-completion.tape

Output "/tmp/_vhs-admin-completion.gif"

Set Shell "bash"
Set FontSize 16
Set Width 1100
Set Height 360
Set Theme "Catppuccin Mocha"
Set TypingSpeed 1ms

Hide
# Open at line 8 (the ``pass`` body) — helix lands cursor at the start
# of the line, which is column 0.
Type "cd docs/screenshots/fixtures/demo_project && hx --config $PWD/.xdg/helix/config.toml admin_completion.py:8"
Enter
Sleep 3s
Show

# ``x`` selects the entire current line; ``d`` deletes it. Then ``O``
# opens an indented line above (cursor sits inside the class body).
Type "xd"
Sleep 100ms
Type "O"
Sleep 200ms
Type "list_display = ('"
Sleep 2s

Screenshot "docs/screenshots/out/admin-completion.png"
Sleep 100ms
