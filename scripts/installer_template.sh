#!/bin/bash
# Quake II with AI-decompiled game code: one-command installer.
#
#   bash QuakeII-AI-installer.sh                   # free demo data: the first 3 levels
#   bash QuakeII-AI-installer.sh /path/to/baseq2   # your own full game copy: all levels
#
# macOS: installs "Quake II AI.app" in ~/Applications (open it to play).
# Linux: installs a "Quake II AI" menu entry.
# Downloads (each checked against a fixed SHA-256): SDL2 2.32.10 and Yamagi Quake II 8.70
# (open source, GPL), and the official free Quake II demo data (id Software; the demo
# licence allows free use, it is not part of this installer). The AI-decompiled game code
# is inside this file. Everything goes into one folder; nothing needs admin rights.
# Uninstall: delete that folder (and the app or menu entry).
set -euo pipefail
OWN="${1:-}"   # optional: baseq2 folder of a Quake II copy you own (pak0.pak, pak1.pak, ...)
[ -z "$OWN" ] || [ -f "$OWN/pak0.pak" ] || { echo "No pak0.pak in '$OWN'. Give the baseq2 folder of your Quake II install." >&2; exit 1; }

SDL_URL=https://github.com/libsdl-org/SDL/releases/download/release-2.32.10/SDL2-2.32.10.tar.gz
SDL_SHA=5f5993c530f084535c65a6879e9b26ad441169b3e25d789d83287040a9ca5165
YQ2_URL=https://github.com/yquake2/yquake2/archive/refs/tags/QUAKE2_8_70.tar.gz
YQ2_SHA=ace0a4eb4326e6406519c1ffe378f08f59080c8d5272e814ee898fa28e5739c2
DEMO_URL=https://deponie.yamagi.org/quake2/idstuff/q2-314-demo-x86.exe
DEMO_SHA=7ace5a43983f10d6bdc9d9b6e17a1032ba6223118d389bd170df89b945a04a1e

OS=$(uname)
if [ "$OS" = Darwin ]; then
  DEST="${Q2AI_DEST:-$HOME/Library/QuakeII-AI}"   # no spaces: the builds break on them
  APP="${Q2AI_APP:-$HOME/Applications/Quake II AI.app}"
  LIB=game.dylib
  JOBS=$(sysctl -n hw.ncpu)
else
  DEST="${Q2AI_DEST:-$HOME/.local/share/QuakeII-AI}"
  LIB=game.so
  JOBS=$(nproc)
fi
SRC="$DEST/src"
step() { printf '\n==> %s\n' "$*"; }
die() { printf '\nInstall failed: %s\n' "$*" >&2; exit 1; }
sha() { if command -v shasum >/dev/null; then shasum -a 256 "$1"; else sha256sum "$1"; fi | cut -d' ' -f1; }
fetch() {   # url sha256 file: download once, verify every time
  if [ ! -f "$3" ]; then
    curl -fL --progress-bar -o "$3.part" "$1" || die "download failed: $1 (check the internet connection, re-run)"
    mv "$3.part" "$3"
  fi
  [ "$(sha "$3")" = "$2" ] || { rm -f "$3"; die "checksum mismatch for $1 (download again by re-running)"; }
}

step "1/6 Checking build tools"
if [ "$OS" = Darwin ] && ! xcode-select -p >/dev/null 2>&1; then
  echo "Apple's command line tools are needed. A system dialog will open: click Install."
  xcode-select --install || true
  until xcode-select -p >/dev/null 2>&1; do sleep 10; done
fi
for t in cc make curl unzip tar; do command -v $t >/dev/null || die "'$t' is missing"; done
case "$DEST" in *" "*) die "install folder must not contain spaces: $DEST";; esac
mkdir -p "$SRC" "$DEST/data/baseq2"

step "2/6 Unpacking the AI game code"
rm -rf "$SRC/ai_source"
N=$(LC_ALL=C grep -an '^__PAYLOAD_BELOW__$' "$0" | cut -d: -f1)   # binary-safe: macOS sed rejects the payload
tail -n +"$((N + 1))" "$0" | tar xz -C "$SRC"

step "3/6 SDL2 (window, input, sound) - about 2 minutes"
if [ ! -f "$DEST/sdl2/.done" ]; then
  fetch "$SDL_URL" "$SDL_SHA" "$SRC/SDL2.tar.gz"
  rm -rf "$SRC/SDL2-2.32.10" && tar xzf "$SRC/SDL2.tar.gz" -C "$SRC"
  (cd "$SRC/SDL2-2.32.10" && ./configure --prefix="$DEST/sdl2" --disable-static >"$SRC/sdl2.log" 2>&1 \
    && make -j"$JOBS" >>"$SRC/sdl2.log" 2>&1 && make install >>"$SRC/sdl2.log" 2>&1) || die "SDL2 build, see $SRC/sdl2.log"
  touch "$DEST/sdl2/.done"
fi

step "4/6 Quake II engine (Yamagi Quake II) - about 1 minute"
if [ ! -x "$DEST/engine/quake2" ]; then
  fetch "$YQ2_URL" "$YQ2_SHA" "$SRC/yquake2.tar.gz"
  rm -rf "$SRC/yquake2-QUAKE2_8_70" && tar xzf "$SRC/yquake2.tar.gz" -C "$SRC"
  yq2() { (cd "$SRC/yquake2-QUAKE2_8_70" && make -j"$JOBS" WITH_SDL3=no WITH_CURL=no WITH_OPENAL=no \
    SDLCFLAGS="-I$DEST/sdl2/include -I$DEST/sdl2/include/SDL2 -D_REENTRANT" SDLLDFLAGS="-L$DEST/sdl2/lib -lSDL2 -Wl,-rpath,$DEST/sdl2/lib" \
    "$@" >>"$SRC/engine.log" 2>&1); }
  yq2 client ref_soft || die "engine build, see $SRC/engine.log"
  yq2 ref_gl1 ref_gl3 || echo "OpenGL renderers not built (no OpenGL headers); the software renderer is used."
  rm -rf "$DEST/engine" && mkdir -p "$DEST/engine"
  cp "$SRC/yquake2-QUAKE2_8_70/release/quake2" "$SRC"/yquake2-QUAKE2_8_70/release/ref_* "$DEST/engine/"
fi

step "5/6 AI game code - about 1 minute"
(cd "$SRC/ai_source" && sh build.sh >"$SRC/game.log" 2>&1) || die "game build, see $SRC/game.log"
cp "$SRC/ai_source/$LIB" "$DEST/data/baseq2/$LIB"

if [ -n "$OWN" ]; then
  step "6/6 Copying your Quake II game data"
  cp "$OWN"/pak*.pak "$DEST/data/baseq2/"
  for d in players video; do [ -d "$OWN/$d" ] && cp -R "$OWN/$d" "$DEST/data/baseq2/"; done
elif [ ! -f "$DEST/data/baseq2/pak0.pak" ]; then
  step "6/6 Quake II demo data: first 3 levels (about 40 MB download)"
  fetch "$DEMO_URL" "$DEMO_SHA" "$SRC/q2demo.exe"
  rm -rf "$SRC/q2demo" && mkdir "$SRC/q2demo"
  unzip -q -o "$SRC/q2demo.exe" 'Install/Data/baseq2/pak0.pak' 'Install/Data/baseq2/players/*' -d "$SRC/q2demo"
  cp -R "$SRC/q2demo/Install/Data/baseq2/." "$DEST/data/baseq2/"
  # the demo data has no intro movie: New Game goes straight to the first level
  echo 'alias newgame "killserver ; maxclients 1 ; deathmatch 0 ; map demo1"' > "$DEST/data/baseq2/autoexec.cfg"
fi

if [ "$OS" = Darwin ]; then CFG="$HOME/Library/Application Support/YamagiQ2/baseq2/config.cfg"; else CFG="$HOME/.local/share/YamagiQ2/baseq2/config.cfg"; fi
# first launch only (no saved settings yet): OpenGL 3, fullscreen at desktop resolution, Retina aware
FIRST=""
[ -f "$DEST/engine/ref_gl3.${LIB##*.}" ] && FIRST="+set vid_renderer gl3 +set r_mode -2 +set vid_fullscreen 2 +set vid_highdpiaware 1"
cat > "$DEST/play.sh" <<EOF
#!/bin/bash
cd "$DEST/engine" || exit 1
if [ -f "$CFG" ]; then exec ./quake2 -datadir "$DEST/data" "\$@"; fi
exec ./quake2 -datadir "$DEST/data" $FIRST "\$@"
EOF
chmod +x "$DEST/play.sh"

if [ "$OS" = Darwin ]; then
  rm -rf "$APP" && mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
  printf '#!/bin/bash\nexec "%s/play.sh" "$@"\n' "$DEST" > "$APP/Contents/MacOS/QuakeIIAI"
  chmod +x "$APP/Contents/MacOS/QuakeIIAI"
  ICON=""
  if [ -f "$SRC/yquake2-QUAKE2_8_70/stuff/icon/Quake2.png" ]; then   # Mac icon from the engine's PNG
    I="$SRC/q2.iconset" && rm -rf "$I" && mkdir "$I"
    for s in 16 32 128 256 512; do
      sips -z $s $s "$SRC/yquake2-QUAKE2_8_70/stuff/icon/Quake2.png" --out "$I/icon_${s}x${s}.png" >/dev/null 2>&1 || true
    done
    iconutil -c icns "$I" -o "$APP/Contents/Resources/QuakeIIAI.icns" 2>/dev/null && ICON="<key>CFBundleIconFile</key><string>QuakeIIAI</string>"
  fi
  cat > "$APP/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleName</key><string>Quake II AI</string>
<key>CFBundleIdentifier</key><string>local.quake2.ai-decompiled</string>
<key>CFBundleExecutable</key><string>QuakeIIAI</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>CFBundleVersion</key><string>1</string>
<key>LSMinimumSystemVersion</key><string>11.0</string>
<key>NSHighResolutionCapable</key><true/>
$ICON
</dict></plist>
EOF
  WHERE="Open 'Quake II AI' from ~/Applications (Finder > Go > Home > Applications), or Spotlight."
else
  mkdir -p "$HOME/.local/share/applications"
  cat > "$HOME/.local/share/applications/quake2-ai.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Quake II AI
Exec="$DEST/play.sh"
Icon=$SRC/yquake2-QUAKE2_8_70/stuff/icon/Quake2.png
Categories=Game;
EOF
  WHERE="Start 'Quake II AI' from the applications menu, or run: $DEST/play.sh"
fi

printf '\nDone. %s\nIn the game: Game > Easy (or Medium/Hard) starts a new game.\n' "$WHERE"
exit 0
__PAYLOAD_BELOW__
