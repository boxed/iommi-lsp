#!/usr/bin/env bash
# Run vhs on the given tapes (or all of them) and crop the resulting PNG
# down to the editor content — Helix renders an empty statusline bar
# below the buffer plus a chunk of dark padding, which vhs has no
# directive to suppress, so we trim it post-hoc.
set -euo pipefail

cd "$(dirname "$0")/../.."

tapes=("$@")
if [[ ${#tapes[@]} -eq 0 ]]; then
  tapes=(docs/screenshots/tapes/*.tape)
fi

# Editor background color matches the Catppuccin Mocha theme set in every
# tape — used as the bordercolor so the post-crop padding blends in.
bg="#1c1c2c"

# Per-tape right-side chop, in pixels. Some demos can't avoid ty
# diagnostics on the right (e.g. a partial kwarg chain looks like an
# unresolved name to ty), so the tape uses a wide terminal to keep the
# popup and the diagnostic separated, and we chop the diagnostic off
# after trim.
declare -A right_chop=()

for tape in "${tapes[@]}"; do
  base="$(basename "$tape")"
  chop="${right_chop[$base]:-0}"
  out="docs/screenshots/out/${base%.tape}.png"
  vhs "$tape" > /dev/null

  magick "$out" \
    -gravity South -chop 0x110 \
    -fuzz 2% -trim +repage \
    "$out"

  if [[ "$chop" -gt 0 ]]; then
    magick "$out" -gravity East -chop "${chop}x0" +repage "$out"
    # The chop exposes raw background on the right — re-trim that, then
    # re-apply the padding border.
    magick "$out" -fuzz 2% -trim +repage "$out"
  fi

  magick "$out" -bordercolor "$bg" -border 20 "$out"

  printf '%s → %s (%s)\n' "$tape" "$out" "$(magick identify -format '%wx%h' "$out")"
done
