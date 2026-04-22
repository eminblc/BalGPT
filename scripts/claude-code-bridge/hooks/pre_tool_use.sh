#!/bin/bash
# PreToolUse hook — Bridge'e araç onayı sorar, defer veya allow döner.
# FEAT-4: Kullanıcı bireysel araç çağrılarını WhatsApp/Telegram butonlarıyla onaylar.
#
# bypassPermissions modunda: doğrudan allow döner (mevcut davranış korunur).
# default modunda: Bridge /perm_check endpoint'ine sorar;
#   - approved → allow
#   - pending  → defer (CLI pause eder, Bridge kullanıcıya buton gönderir)
#   - Bridge yoksa → allow (güvenli taraf)

PERM_MODE="${CLAUDE_CODE_PERMISSIONS:-bypassPermissions}"
BRIDGE_URL="${CLAUDE_BRIDGE_URL:-http://localhost:8013}"

# bypassPermissions modunda doğrudan onayla
if [ "$PERM_MODE" = "bypassPermissions" ]; then
  echo '{"decision":"approve"}'
  exit 0
fi

# Tool bilgisini stdin'den oku ve Bridge'e gönder
TOOL_INFO=$(cat)
RESPONSE=$(printf '%s' "$TOOL_INFO" | \
  curl -sf -X POST "${BRIDGE_URL}/perm_check" \
    -H "Content-Type: application/json" \
    -d @- \
    --max-time 5 \
    --no-progress-meter \
    2>/dev/null | head -1)

if [ -z "$RESPONSE" ]; then
  # Bridge'e ulaşılamazsa onayla (güvenli taraf — Bridge yoksa engelleme)
  echo '{"decision":"approve"}'
else
  echo "$RESPONSE"
fi
