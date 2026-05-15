# Signal-sender completion inside @receiver(post_save, sender=...).
#
# Regenerate with: vhs docs/screenshots/tapes/signal-completion.tape

Output "/tmp/_vhs-signal-completion.gif"

Set Shell "bash"
Set FontSize 16
Set Width 1100
Set Height 360
Set Theme "Catppuccin Mocha"
Set TypingSpeed 1ms

Hide
Type "cd docs/screenshots/fixtures/demo_project && hx --config $PWD/.xdg/helix/config.toml signal_completion.py"
Enter
Sleep 3s
Show

Type "Go"
Sleep 200ms
Type "@receiver(post_save, sender="
Sleep 2s

Screenshot "docs/screenshots/out/signal-completion.png"
Sleep 100ms
