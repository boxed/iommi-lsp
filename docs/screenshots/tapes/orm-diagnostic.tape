# Typo in an ORM kwarg gets flagged: `eemail` is not a field on User, so
# iommi_lsp emits `django-unknown-orm-lookup`.
#
# Regenerate with: docs/screenshots/regenerate.sh docs/screenshots/tapes/orm-diagnostic.tape

Output "/tmp/_vhs-orm-diagnostic.gif"

Set Shell "bash"
Set FontSize 16
Set Width 1100
Set Height 360
Set Theme "Catppuccin Mocha"
Set TypingSpeed 1ms

Hide
Type "cd docs/screenshots/fixtures/demo_project && hx --config $PWD/.xdg/helix/config.toml diagnostic.py"
Enter
Sleep 3s
Show

# Complete kwarg with a typo. Escape to normal mode and `gh` parks the
# cursor at column 0 of the same line; inline-diagnostic fires per-line
# regardless of which column the cursor is on, and starting at column 0
# avoids a selection highlight overlapping `eemail` (which would render
# the word unreadable).
Type "oUser.objects.filter(eemail='x')"
Escape
Type "gh"
Sleep 2s

Screenshot "docs/screenshots/out/orm-diagnostic.png"
Sleep 100ms
