# URL-name completion inside reverse('...')
#
# Regenerate with: vhs docs/screenshots/tapes/url-completion.tape
# (run from the project root)

Output "/tmp/_vhs-url-completion.gif"

Set Shell "bash"
Set FontSize 16
Set Width 1100
Set Height 360
Set Theme "Catppuccin Mocha"
Set TypingSpeed 1ms

Hide
Type "cd docs/screenshots/fixtures/demo_project && hx --config $PWD/.xdg/helix/config.toml url_completion.py"
Enter
Sleep 3s
Show

# Stop right after the open quote — the LSP fires URL-name completion.
Type "oreverse('"
Sleep 2s

Screenshot "docs/screenshots/out/url-completion.png"
Sleep 100ms
