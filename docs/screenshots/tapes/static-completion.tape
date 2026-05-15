# Staticfiles completion inside static('...').
#
# Regenerate with: vhs docs/screenshots/tapes/static-completion.tape

Output "/tmp/_vhs-static-completion.gif"

Set Shell "bash"
Set FontSize 16
Set Width 1100
Set Height 360
Set Theme "Catppuccin Mocha"
Set TypingSpeed 1ms

Hide
Type "cd docs/screenshots/fixtures/demo_project && hx --config $PWD/.xdg/helix/config.toml static_completion.py"
Enter
Sleep 3s
Show

Type "ourl = static('"
Sleep 2s

Screenshot "docs/screenshots/out/static-completion.png"
Sleep 100ms
