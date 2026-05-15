# iommi `post_handler` (and friends) receive a string literal — almost
# always a typo where the user accidentally quoted a callable name.
#
# Regenerate with: docs/screenshots/regenerate.sh docs/screenshots/tapes/iommi-callable.tape

Output "/tmp/_vhs-iommi-callable.gif"

Set Shell "bash"
Set FontSize 16
Set Width 1100
Set Height 300
Set Theme "Catppuccin Mocha"
Set TypingSpeed 1ms

Hide
Type "cd docs/screenshots/fixtures/demo_project && hx --config $PWD/.xdg/helix/config.toml iommi_callable.py:3"
Enter
Sleep 3s
Show

Type "oAction(post_handler='save_widget')"
Escape
Type "gh"
Sleep 2s

Screenshot "docs/screenshots/out/iommi-callable.png"
Sleep 100ms
