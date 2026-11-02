#!/usr/bin/env bash
# Comprueba que ningún binario del .app exige un macOS más nuevo que $1 (p. ej. 11.0).
set -euo pipefail
app="$1"; max="$2"
bad=0
while IFS= read -r -d '' f; do
  file -b "$f" | grep -q "Mach-O" || continue
  minos=$(otool -l "$f" 2>/dev/null | awk '/LC_BUILD_VERSION/{b=1} b&&/minos/{print $2; exit} /LC_VERSION_MIN_MACOSX/{v=1} v&&/version/{print $2; exit}')
  [ -z "$minos" ] && continue
  if [ "$(printf '%s\n%s\n' "$minos" "$max" | sort -V | tail -1)" != "$max" ]; then
    echo "Requiere macOS $minos: ${f#$app/}"; bad=1
  fi
done < <(find "$app" -type f -print0)
[ "$bad" = 0 ] && echo "Todos los binarios funcionan en macOS $max o posterior."
exit "$bad"
