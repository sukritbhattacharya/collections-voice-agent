#!/usr/bin/env bash
# Expose the local call client over HTTPS so a phone can use its microphone.
#
# Browsers only grant getUserMedia in a secure context. http://localhost
# qualifies; http://192.168.x.x does not -- which means a phone pointed at the
# laptop's LAN address gets a silent permission failure that looks like a
# broken app. A tunnel is the shortest way to a real certificate.
#
#   ./scripts/tunnel.sh
#
# Prints a QR code if `qrencode` is installed (brew install qrencode), so the
# phone can scan rather than type the URL.

set -euo pipefail
PORT="${WEB_PORT:-8080}"

if ! command -v cloudflared >/dev/null 2>&1; then
  echo "cloudflared is not installed."
  echo "  brew install cloudflared"
  echo
  echo "Alternative: ngrok http ${PORT}"
  exit 1
fi

if ! curl -sf "http://localhost:${PORT}/" >/dev/null 2>&1; then
  echo "Nothing is serving on port ${PORT}."
  echo "  Start it first:  uv run python -m src.voice.web_server"
  exit 1
fi

echo "Opening an HTTPS tunnel to localhost:${PORT} ..."
echo "Scan or open the trycloudflare.com URL below on your phone."
echo

cloudflared tunnel --url "http://localhost:${PORT}" 2>&1 | while IFS= read -r line; do
  echo "$line"
  if [[ "$line" =~ (https://[a-z0-9-]+\.trycloudflare\.com) ]]; then
    url="${BASH_REMATCH[1]}"
    echo
    echo "  ===> $url"
    echo
    if command -v qrencode >/dev/null 2>&1; then
      qrencode -t ANSIUTF8 "$url"
    else
      echo "  (brew install qrencode to get a scannable QR code here)"
    fi
    echo
  fi
done
