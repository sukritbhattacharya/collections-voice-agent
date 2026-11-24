#!/usr/bin/env bash
# One command to bring the demo up and prove it works.
#
# Three things expire or die between sessions and each fails differently:
# the Cloudflare hostname is revoked (the page stops loading), the free
# webhook endpoint fills at 50 requests and is then disabled (calls succeed
# and the CRM pane stays empty), and a laptop that slept leaves processes
# running but unregistered. This checks all three, and prints a QR.
#
#   ./scripts/preflight.sh
set -u
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
LOGS="${TMPDIR:-/tmp}/collections-demo"; mkdir -p "$LOGS"

say() { printf "\n\033[1m%s\033[0m\n" "$1"; }
ok()  { printf "  \033[32mok\033[0m    %s\n" "$1"; }
bad() { printf "  \033[31mFAIL\033[0m  %s\n" "$1"; }

say "1. Restarting the services"
pkill -f "src.voice.agent" 2>/dev/null; pkill -f "src.voice.web_server" 2>/dev/null
pkill -f cloudflared 2>/dev/null; sleep 2
nohup uv run python -m src.voice.web_server >> "$LOGS/web.log" 2>&1 &
sleep 3
nohup uv run python -m src.voice.agent dev   >> "$LOGS/agent.log" 2>&1 &
nohup cloudflared tunnel --url http://localhost:8080 > "$LOGS/tunnel.log" 2>&1 &
sleep 12

curl -fsS --max-time 5 http://localhost:8080/ >/dev/null 2>&1 \
  && ok "web server on :8080" || bad "web server is not answering"
grep -q "registered worker" "$LOGS/agent.log" 2>/dev/null \
  && ok "voice worker registered with LiveKit" || bad "worker did not register"

say "2. Public URL"
URL=""
for _ in $(seq 1 20); do
  URL=$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOGS/tunnel.log" 2>/dev/null | head -1)
  [ -n "$URL" ] && break
  sleep 2
done
if [ -z "$URL" ]; then bad "no tunnel URL yet; check $LOGS/tunnel.log"; else
  echo "$URL" > "$LOGS/tunnel_url.txt"
  for p in / /dashboard /api/personas; do
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$URL$p")
    [ "$code" = "200" ] && ok "$code  $URL$p" || bad "$code  $URL$p"
  done
fi

say "3. Credentials and the CRM endpoint"
uv run python scripts/check_setup.py 2>&1 | sed -n '/Checking/,$p' | sed 's/^/  /'

say "4. A real call, end to end"
set -a; . ./.env 2>/dev/null; set +a
if timeout 120 uv run python scripts/voice_smoke_test.py MB-4471 >"$LOGS/smoke.log" 2>&1; then
  ok "$(grep -E 'time to first audio' "$LOGS/smoke.log" | tr -s ' ')"
  sleep 4
  TOKEN=$(printf '%s' "${OUTCOME_WEBHOOK_URL:-}" | sed -E 's#.*/([0-9a-f-]{36}).*#\1#')
  if [ -n "$TOKEN" ]; then
    n=$(curl -s --max-time 10 "https://webhook.site/token/$TOKEN/requests?per_page=1" \
        | python3 -c "import sys,json;print(json.load(sys.stdin).get('total','?'))" 2>/dev/null)
    ok "outcomes reaching the CRM endpoint (${n} stored)"
  fi
else
  bad "smoke test failed; see $LOGS/smoke.log"
fi

say "5. QR for the handsets"
[ -n "$URL" ] && uv run --with "qrcode[pil]" python - "$URL" <<'PY'
import sys, qrcode
q = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=2)
q.add_data(sys.argv[1]); q.make(fit=True)
m = q.get_matrix()
for y in range(0, len(m), 2):
    top = m[y]; bot = m[y+1] if y+1 < len(m) else [False]*len(top)
    print("  " + "".join("█" if t and b else "▀" if t else "▄" if b else " "
                         for t, b in zip(top, bot)))
print(f"\n  {sys.argv[1]}")
PY
printf "\n"
