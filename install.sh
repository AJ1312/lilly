#!/usr/bin/env bash
# Installs Lilly for the current user: a private Python environment, the `lilly` command and,
# on macOS, a Lilly app in ~/Applications. Safe to run again to update.
#
#   ./install.sh                 install (or update)
#   ./install.sh --login-item    also start Lilly automatically when you log in (macOS)
#   ./install.sh --no-open       do not open Lilly in the browser at the end
#   ./install.sh --no-laya       skip Laya, the helper model that saves tokens (about 850 MB plus packages)
#
# Laya is set up by default, after a check of this computer and followed by a test. If that fails, Lilly is still
# installed and works without it; set it up later from Settings → Quick decisions → Laya or with `lilly laya check`
# (see docs/LAYA.md).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="${LILLY_APP_DIR:-$HOME/.local/share/lilly-app}"   # the program (data lives in ~/.lilly)
BIN_DIR="${LILLY_BIN_DIR:-$HOME/.local/bin}"
LOGIN_ITEM=0
OPEN=1
LAYA=1
for arg in "$@"; do
  case "$arg" in
    --login-item) LOGIN_ITEM=1 ;;
    --no-open) OPEN=0 ;;
    --no-laya) LAYA=0 ;;
    -h|--help) sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unknown option: $arg" >&2; exit 2 ;;
  esac
done

say() { printf '\n==> %s\n' "$*"; }
die() { printf '\nLilly could not be installed: %s\n' "$*" >&2; exit 1; }

# 1. Python 3.12 or newer
PYTHON=""
for candidate in python3.14 python3.13 python3.12 python3 python; do
  if command -v "$candidate" >/dev/null 2>&1 \
     && "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 12))' 2>/dev/null; then
    PYTHON="$(command -v "$candidate")"; break
  fi
done
[ -n "$PYTHON" ] || die "Python 3.12 or newer is required. On a Mac: install it from https://www.python.org/downloads/ or run 'brew install python', then run this again."
say "Using $("$PYTHON" --version) at $PYTHON"

# 2. Private environment and the program
say "Installing Lilly into $APP_DIR"
mkdir -p "$APP_DIR"
"$PYTHON" -m venv "$APP_DIR/venv" || die "could not create a Python environment (on Debian/Ubuntu: sudo apt install python3-venv)"
"$APP_DIR/venv/bin/python" -m pip install --quiet --upgrade pip
"$APP_DIR/venv/bin/python" -m pip install --quiet --upgrade "$HERE" || die "pip could not install Lilly and its dependencies (is this computer online?)"
[ -f "$("$APP_DIR/venv/bin/python" -c 'import lilly, pathlib; print(pathlib.Path(lilly.__file__).parent / "web" / "index.html")')" ] \
  || die "the interface files are missing from this copy of Lilly"

# 3. The `lilly` command
mkdir -p "$BIN_DIR"
ln -sf "$APP_DIR/venv/bin/lilly" "$BIN_DIR/lilly"
case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) echo "Note: $BIN_DIR is not on your PATH. Add this to your shell profile:  export PATH=\"$BIN_DIR:\$PATH\"" ;;
esac

# 3b. Laya, a small helper model that answers quick routing questions so fewer tokens go to the language model. It
#     lives in its own environment, is fetched from a pinned Hugging Face commit and checked against reviewed hashes,
#     and is turned on only after it has passed its own test. A failure here never fails the install.
if [ "$LAYA" = 1 ]; then
  say "Setting up Laya (a download of about 850 MB; skip it with --no-laya)"
  if "$APP_DIR/venv/bin/lilly" laya check && "$APP_DIR/venv/bin/lilly" laya install \
     && "$APP_DIR/venv/bin/lilly" laya test; then
    "$APP_DIR/venv/bin/lilly" laya enable || true
  else
    echo "Note: Laya was not set up. Lilly works without it; see docs/LAYA.md, or try again from Settings → Quick decisions."
  fi
fi

# 4. macOS: a Lilly app that opens the interface (starting Lilly first if needed)
if [ "$(uname -s)" = "Darwin" ]; then
  APP="$HOME/Applications/Lilly.app"
  say "Creating $APP"
  rm -rf "$APP"
  mkdir -p "$APP/Contents/MacOS"
  cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>Lilly</string>
  <key>CFBundleIdentifier</key><string>app.lilly.launcher</string>
  <key>CFBundleExecutable</key><string>Lilly</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>LSUIElement</key><true/>
</dict></plist>
PLIST
  cat > "$APP/Contents/MacOS/Lilly" <<LAUNCH
#!/bin/bash
exec "$APP_DIR/venv/bin/lilly" open
LAUNCH
  chmod +x "$APP/Contents/MacOS/Lilly"
  if [ "$LOGIN_ITEM" = 1 ]; then
    say "Starting Lilly at login"
    "$APP_DIR/venv/bin/lilly" install-service
  fi
elif [ "$LOGIN_ITEM" = 1 ]; then
  echo "Note: --login-item is only available on macOS; start Lilly with 'lilly run'."
fi

say "Lilly is installed."
echo "  Open it any time:   lilly open        (or the Lilly app in ~/Applications on a Mac)"
echo "  Stop it:            lilly stop"
echo "  Your data:          ~/.lilly          (private to you; back it up from Settings → Data)"
echo "  Next:               Settings → Models & keys, to add a free API key (see docs/SETUP.md)."
if "$APP_DIR/venv/bin/lilly" laya status 2>/dev/null | grep -q "^installed: yes"; then
  echo "  Laya:               installed and turned on (Settings → Quick decisions → Laya shows its state)."
elif [ "$LAYA" = 1 ]; then
  echo "  Laya:               not set up (see the note above); Settings → Quick decisions → Laya shows why and can retry."
else
  echo "  Laya:               skipped; Settings → Quick decisions → Laya can set it up later (docs/LAYA.md)."
fi
if [ "$OPEN" = 1 ]; then
  "$APP_DIR/venv/bin/lilly" open || echo "Run 'lilly open' to start it."
fi
