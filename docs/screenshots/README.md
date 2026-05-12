# Feature screenshots

Each `tapes/*.tape` drives Helix (with `iommi_lsp` configured) through a
canned interaction and saves a still PNG into `out/`. Used for the README
and docs site.

## Prereqs

```sh
brew install vhs ttyd ffmpeg imagemagick
uv tool install -e .          # so `iommi_lsp` is on PATH
```

The fixture under `fixtures/demo_project/` carries its own
`.helix/languages.toml` (registers `iommi_lsp` for Python) and
`.xdg/helix/config.toml` (hides the gutter + empties the statusline).
The tape passes the latter to Helix via `hx --config $PWD/.xdg/...` —
Helix 25.07 ignores `.helix/config.toml` and `XDG_CONFIG_HOME`, so the
explicit `--config` is the only path that actually loads those tweaks.

vhs 0.11 requires an `Output` directive but only writes `.gif`/`.mp4`/
`.webm` — not `.png`. The tapes write the gif to `/tmp` (throwaway) and
use vhs's separate `Screenshot` directive for the still that actually
gets committed.

## Regenerate

```sh
# one tape
docs/screenshots/regenerate.sh docs/screenshots/tapes/orm-completion.tape

# all tapes
docs/screenshots/regenerate.sh
```

`regenerate.sh` runs vhs to record the PNG, then crops it via
ImageMagick — Helix renders an empty statusline bar plus dark padding
that vhs has no directive to suppress, so we strip it post-hoc.

Outputs land in `docs/screenshots/out/`. Commit the PNGs — they're the
source of truth that gets embedded in docs; vhs output is not byte-stable
across terminal versions, so we don't diff them in CI.

## Adding a tape

1. Pick the feature and the smallest fixture that demonstrates it. Add
   files under `fixtures/demo_project/` if needed.
2. Copy `tapes/orm-completion.tape` as a starting point. The opening
   `cd ... && hx ...` boilerplate is the same for every tape.
3. Tune the `Sleep` after `hx` boot — LSP cold-start time depends on the
   workspace size. 3s is usually enough for the demo fixture; bump it
   for larger fixtures.
4. Keep a `Sleep` after the `Screenshot` directive (~100ms is plenty) —
   vhs buffers the PNG write and skipping the trailing sleep means the
   file doesn't get flushed.
5. Run `vhs <your.tape>` locally, eyeball the PNG, iterate.
