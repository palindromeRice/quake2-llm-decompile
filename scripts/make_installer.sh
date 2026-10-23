#!/bin/sh
# Pack the AI source tree into the one-file installer (installer_template.sh + tar.gz payload).
# Usage: scripts/make_installer.sh [build/ai_source] [QuakeII-AI-installer.sh]
set -e
TREE="${1:-build/ai_source}"
OUT="${2:-QuakeII-AI-installer.sh}"
{ cat "$(dirname "$0")/installer_template.sh"
  tar czf - --no-xattrs -C "$(dirname "$TREE")" --exclude=obj --exclude=game.so --exclude=game.dylib "$(basename "$TREE")"
} > "$OUT"
chmod +x "$OUT"
echo "$OUT ($(du -h "$OUT" | cut -f1))"
