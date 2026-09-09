#!/bin/zsh
set -euo pipefail

CONFIG_DIR="$HOME/.config/ultralearn"
CONFIG="$CONFIG_DIR/env"
mkdir -p "$CONFIG_DIR"

echo
echo "Ultralearn — save CURSOR_API_KEY on this Mac"
echo "Paste the key, then press Enter. It will not be shown."
echo
printf "CURSOR_API_KEY: "
read -rs KEY
echo
KEY="${KEY//$'\r'/}"
KEY="${KEY#"${KEY%%[![:space:]]*}"}"
KEY="${KEY%"${KEY##*[![:space:]]}"}"

if [[ -z "$KEY" ]]; then
  echo "No key entered. Nothing was saved."
  echo
  echo "Press Enter to close."
  read -r
  exit 1
fi

touch "$CONFIG"
if grep -q '^CURSOR_API_KEY=' "$CONFIG" 2>/dev/null; then
  grep -v '^CURSOR_API_KEY=' "$CONFIG" > "$CONFIG.tmp" || true
  mv "$CONFIG.tmp" "$CONFIG"
fi
printf 'CURSOR_API_KEY=%s\n' "$KEY" >> "$CONFIG"
chmod 600 "$CONFIG"

MARKER="# Ultralearn local secrets"
ZSHRC="$HOME/.zshrc"
if [[ -f "$ZSHRC" ]] && grep -q "$MARKER" "$ZSHRC"; then
  :
else
  {
    echo ""
    echo "$MARKER"
    echo '[ -f "$HOME/.config/ultralearn/env" ] && set -a && . "$HOME/.config/ultralearn/env" && set +a'
  } >> "$ZSHRC"
fi

echo "Saved to $CONFIG (mode 600)."
echo "New terminals will load it via ~/.zshrc."
echo "Restart Ultralearn so this launch picks it up."
echo
echo "Press Enter to close."
read -r
