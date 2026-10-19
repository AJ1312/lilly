#!/usr/bin/env bash
# Removes Lilly's program, command and launcher. Your data in ~/.lilly is kept unless you pass --purge-data.
set -euo pipefail

APP_DIR="${LILLY_APP_DIR:-${HOME:-$PWD}/.local/share/lilly-app}"
BIN_DIR="${LILLY_BIN_DIR:-${HOME:-$PWD}/.local/bin}"
HOME_DIR="${LILLY_HOME:-${HOME:-$PWD}/.lilly}"
PURGE=0
[ "${1:-}" = "--purge-data" ] && PURGE=1

if [ -x "$APP_DIR/venv/bin/lilly" ]; then
  "$APP_DIR/venv/bin/lilly" stop 2>/dev/null || true
  "$APP_DIR/venv/bin/lilly" uninstall-service 2>/dev/null || true
fi
rm -f "$BIN_DIR/lilly"
rm -rf "$APP_DIR"
if [ -n "${HOME:-}" ]; then
  rm -rf "$HOME/Applications/Lilly.app"
fi

if [ "$PURGE" = 1 ]; then
  rm -rf "$HOME_DIR"
  echo "Lilly and all of its data were removed. API keys stored in the macOS Keychain (service 'lilly') remain until you delete them in Keychain Access."
else
  echo "Lilly was removed. Your data is still in $HOME_DIR (run with --purge-data to delete it too)."
fi
