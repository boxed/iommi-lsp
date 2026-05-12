# ORM kwarg completion inside User.objects.filter(...)
#
# Regenerate with: vhs docs/screenshots/tapes/orm-completion.tape
# (run from the project root)

# vhs 0.11 requires an Output directive but only supports gif/mp4/webm.
# Write the GIF to /tmp so we don't commit it; the PNG via Screenshot is
# the real artifact.
Output "/tmp/_vhs-orm-completion.gif"

Set Shell "bash"
Set FontSize 16
Set Width 1100
Set Height 360
Set Theme "Catppuccin Mocha"
Set TypingSpeed 1ms

# --config <abs> is the only path Helix 25.07 honors for editor config
# (.helix/config.toml and XDG_CONFIG_HOME are both ignored).
Hide
Type "cd docs/screenshots/fixtures/demo_project && hx --config $PWD/.xdg/helix/config.toml demo.py"
Enter
Sleep 3s
Show

# Stop at `(` — LSP completion trigger char, so the popup fires without
# typing a partial. No half-typed name → no ty diagnostic to fight.
Type "oUser.objects.filter("
Sleep 2s

Screenshot "docs/screenshots/out/orm-completion.png"
Sleep 100ms
