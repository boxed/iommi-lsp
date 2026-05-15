# {% url 'name' %} completion inside an HTML template. The URL index
# the LSP builds at workspace init time is shared between Python
# (`reverse('...')`) and the template tag.
#
# Regenerate with: docs/screenshots/regenerate.sh docs/screenshots/tapes/template-url-tag.tape

Output "/tmp/_vhs-template-url-tag.gif"

Set Shell "bash"
Set FontSize 16
Set Width 1100
Set Height 360
Set Theme "Catppuccin Mocha"
Set TypingSpeed 1ms

Hide
Type "cd docs/screenshots/fixtures/demo_project && hx --config $PWD/.xdg/helix/config.toml template_url_tag.html"
Enter
Sleep 4s
Show

# `o` opens a fresh line below; type the in-progress {% url 'partial.
Type `o<a href="{% url '`
Sleep 2s

Screenshot "docs/screenshots/out/template-url-tag.png"
Sleep 100ms
