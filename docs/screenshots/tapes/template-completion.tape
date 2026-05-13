# Template-name completion inside a string literal. The TemplateAnalyzer
# discovers every file under a `templates/` directory at LSP init; once
# the cursor sits inside a single-line string whose pre-cursor content
# contains `/`, matching template names are offered.
#
# Regenerate with: docs/screenshots/regenerate.sh docs/screenshots/tapes/template-completion.tape

Output "/tmp/_vhs-template-completion.gif"

Set Shell "bash"
Set FontSize 16
Set Width 1100
Set Height 360
Set Theme "Catppuccin Mocha"
Set TypingSpeed 1ms

Hide
Type "cd docs/screenshots/fixtures/demo_project && hx --config $PWD/.xdg/helix/config.toml template_completion.py"
Enter
Sleep 3s
Show

# `ge` jumps to the last buffer line (the lone import); `o` opens a new
# line below. The string partial `'myapp/` carries the slash that the
# template analyzer takes as its trigger.
Type "georender(request, 'myapp/"
Sleep 2s

Screenshot "docs/screenshots/out/template-completion.png"
Sleep 100ms
