#!/usr/bin/env bash
# lib/messenger.sh — WhatsApp/Telegram notify + bot wizard runner.
#
# Sourced by install.sh; do not execute directly.
# shellcheck shell=bash

_wa_notify() {
  local _tok="$1" _pid="$2" _owner="${3#+}" _msg="$4"
  [ -z "$_tok" ] || [ -z "$_pid" ] || [ -z "$_owner" ] && return 0
  local _body
  _body="$("$PY" -c "
import sys, json
msg, owner = sys.argv[1], sys.argv[2]
print(json.dumps({'messaging_product':'whatsapp','to':owner,'type':'text','text':{'body':msg}}))
" "$_msg" "$_owner" 2>/dev/null)" || return 0
  curl -s --max-time 10 \
    -H "Authorization: Bearer $_tok" \
    -H "Content-Type: application/json" \
    -d "$_body" \
    "https://graph.facebook.com/${_WA_API_VER}/$_pid/messages" \
    >/dev/null 2>&1 || true
}


_tg_notify() {
  local _tok="$1" _cid="$2" _msg="$3"
  [ -z "$_tok" ] || [ -z "$_cid" ] && return 0
  local _body
  _body="$("$PY" -c "import sys,json; print(json.dumps({'chat_id':int(sys.argv[1]),'text':sys.argv[2]}))" \
    "$_cid" "$_msg" 2>/dev/null)" || return 0
  curl -s --max-time 10 \
    -H "Content-Type: application/json" \
    -d "$_body" \
    "https://api.telegram.org/bot${_tok}/sendMessage" \
    >/dev/null 2>&1 || true
}


# Returns current max_update_id+1 so callers can ignore older updates.
_tg_get_offset() {
  local _tok="$1"
  "$PY" -c "
import sys, json, urllib.request
try:
    with urllib.request.urlopen(
        f'https://api.telegram.org/bot{sys.argv[1]}/getUpdates?limit=100&timeout=0', timeout=5
    ) as r:
        d = json.load(r)
    results = d.get('result', [])
    print((results[-1]['update_id'] + 1) if results else 0)
except Exception:
    print(0)
" "$_tok" 2>/dev/null || echo "0"
}


# Send a message with inline keyboard buttons.
# Usage: _tg_send_buttons TOKEN CHAT_ID TEXT "Label:callback_data" ... ["|"] ...
# Use "|" as an argument to start a new button row.
_tg_send_buttons() {
  local _tok="$1" _cid="$2" _txt="$3"
  shift 3
  "$PY" -c "
import sys, json, urllib.request
tok, cid, txt = sys.argv[1], int(sys.argv[2]), sys.argv[3]
rows, row = [], []
for b in sys.argv[4:]:
    if b == '|':
        if row: rows.append(row); row = []
    else:
        label, _, data = b.partition(':')
        row.append({'text': label, 'callback_data': data})
if row:
    rows.append(row)
payload = {'chat_id': cid, 'text': txt, 'parse_mode': 'Markdown',
           'reply_markup': {'inline_keyboard': rows}}
req = urllib.request.Request(
    f'https://api.telegram.org/bot{tok}/sendMessage',
    data=json.dumps(payload).encode(),
    headers={'Content-Type': 'application/json'})
with urllib.request.urlopen(req, timeout=10) as r:
    print(json.load(r)['result']['message_id'])
" "$_tok" "$_cid" "$_txt" "$@" 2>/dev/null || true
}


# Answer a callback query to dismiss the loading spinner in Telegram.
_tg_answer_callback() {
  local _tok="$1" _cb_id="$2"
  curl -s --max-time 5 \
    -d "callback_query_id=${_cb_id}" \
    "https://api.telegram.org/bot${_tok}/answerCallbackQuery" >/dev/null 2>&1 || true
}


# Poll for a callback_query from CHAT_ID starting at OFFSET, up to TIMEOUT seconds.
# Prints "UPDATE_ID CALLBACK_ID CALLBACK_DATA" on success; exits 1 on timeout.
_tg_poll_callback() {
  local _tok="$1" _cid="$2" _offset="${3:-0}" _timeout="${4:-120}"
  "$PY" -c "
import sys, json, urllib.request, time
tok, cid, offset, timeout = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4])
deadline = time.time() + timeout
while time.time() < deadline:
    remaining = max(1, min(30, int(deadline - time.time())))
    url = (f'https://api.telegram.org/bot{tok}/getUpdates'
           f'?timeout={remaining}&limit=10&offset={offset}&allowed_updates=callback_query')
    try:
        with urllib.request.urlopen(url, timeout=remaining + 5) as r:
            d = json.load(r)
        for u in d.get('result', []):
            uid = u['update_id']
            if 'callback_query' in u:
                cb = u['callback_query']
                if cb['message']['chat']['id'] == cid:
                    print(uid, cb['id'], cb['data'])
                    sys.exit(0)
            offset = uid + 1
    except Exception:
        time.sleep(2)
sys.exit(1)
" "$_tok" "$_cid" "$_offset" "$_timeout" 2>/dev/null
}


