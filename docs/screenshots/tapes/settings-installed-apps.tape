# INSTALLED_APPS completion: inside an open string literal that is
# syntactically a value of the INSTALLED_APPS list, the SettingsAnalyzer
# suggests django.contrib.* apps, iommi's AppConfig, and any workspace
# package containing an apps.py (or implicit app — here `myapp`).
#
# Regenerate with: docs/screenshots/regenerate.sh docs/screenshots/tapes/settings-installed-apps.tape

Output "/tmp/_vhs-settings-installed-apps.gif"

Set Shell "bash"
Set FontSize 16
Set Width 1100
Set Height 360
Set Theme "Catppuccin Mocha"
Set TypingSpeed 1ms

Hide
Type "cd docs/screenshots/fixtures/demo_project && hx --config $PWD/.xdg/helix/config.toml settings_completion.py"
Enter
Sleep 3s
Show

# `j` drops onto line 2 (the closing `]`); `O` opens a new line above —
# i.e. between the `[` and `]` — entering insert mode there. The partial
# `'django.contrib.` triggers INSTALLED_APPS completion.
Type "j"
Type "O'django.contrib."
Sleep 2s

Screenshot "docs/screenshots/out/settings-installed-apps.png"
Sleep 100ms
