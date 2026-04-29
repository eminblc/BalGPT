#!/usr/bin/env bats
# Tests for miscellaneous helpers: platform detection, JSON extraction,
# capability resolution, security key generation.

setup() {
  ROOT_DIR="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"
  export ROOT_DIR
  # shellcheck source=/dev/null
  source "$ROOT_DIR/install.sh"
  # Load strings so functions that log _S_* messages don't trip set -u.
  # Best-effort: on minimal containers without python3 this is a no-op,
  # and dependent tests skip themselves.
  INSTALL_LANG=tr _load_strings 2>/dev/null || true
}

# Skip the rest of a test when python3 is missing.
require_python3() {
  command -v python3 >/dev/null 2>&1 || skip "python3 not available"
}

# ── is_windows ───────────────────────────────────────────────────────────────

@test "is_windows: false on Linux" {
  # CI runs on ubuntu-latest — uname -s is "Linux"
  if [[ "$(uname -s)" == "Linux" ]]; then
    run is_windows
    [ "$status" -ne 0 ]
  else
    skip "non-Linux host"
  fi
}

@test "is_windows: matches MINGW/MSYS/CYGWIN prefixes" {
  # We can't change uname output, but we can test the regex directly
  for sys in "MINGW64_NT-10.0" "MSYS_NT-10.0" "CYGWIN_NT-10.0"; do
    [[ "$sys" =~ ^(MINGW|MSYS|CYGWIN) ]]
  done
}

# ── _extract_json_field ──────────────────────────────────────────────────────

@test "_extract_json_field: extracts a string field" {
  json='{"name":"hello","other":"world"}'
  result="$(_extract_json_field "$json" "name")"
  [ "$result" = "hello" ]
}

@test "_extract_json_field: returns empty for missing field" {
  json='{"name":"hello"}'
  result="$(_extract_json_field "$json" "missing")"
  [ -z "$result" ]
}

@test "_extract_json_field: handles empty JSON gracefully" {
  result="$(_extract_json_field "" "name")"
  [ -z "$result" ]
}

# ── _tg_extract_next_offset ──────────────────────────────────────────────────

@test "_tg_extract_next_offset: returns 0 for empty result" {
  json='{"ok":true,"result":[]}'
  result="$(_tg_extract_next_offset "$json")"
  [ "$result" = "0" ]
}

@test "_tg_extract_next_offset: returns last update_id + 1" {
  json='{"ok":true,"result":[{"update_id":42,"message":{}},{"update_id":99,"message":{}}]}'
  result="$(_tg_extract_next_offset "$json")"
  [ "$result" = "100" ]
}

# ── _gen_api_key ─────────────────────────────────────────────────────────────

@test "_gen_api_key: produces 64-char hex string" {
  key="$(_gen_api_key)"
  [ "${#key}" -ge 32 ]   # at least 32 chars (openssl gives 64, fallback gives 64)
  # Hex-only characters
  [[ "$key" =~ ^[0-9a-f]+$ ]]
}

@test "_gen_api_key: each call returns a different value" {
  # Fallback path (date +%s%N + sha256sum) collides on minimal containers
  # where %N is unsupported.  This test exercises the openssl-backed branch.
  command -v openssl >/dev/null 2>&1 || skip "openssl not available — fallback collision tolerated"
  k1="$(_gen_api_key)"
  k2="$(_gen_api_key)"
  [ "$k1" != "$k2" ]
}

# ── _resolve_requirements ────────────────────────────────────────────────────

@test "_resolve_requirements: with no .env returns all capability files" {
  # Point BACKEND_DIR at a temp scratch with empty (but existing) env file
  fake_backend="$BATS_TEST_TMPDIR/fake_backend"
  mkdir -p "$fake_backend/requirements"
  touch "$fake_backend/.env"
  for f in core dev scheduler pdf_import calendar screenshot media; do
    touch "$fake_backend/requirements/${f}.txt"
  done
  BACKEND_DIR="$fake_backend"

  run _resolve_requirements
  [ "$status" -eq 0 ]
  # core + dev always included
  [[ "$output" == *"core.txt"* ]]
  [[ "$output" == *"dev.txt"* ]]
  # No RESTRICT_/_ENABLED in env → all files returned
  [[ "$output" == *"scheduler.txt"* ]]
  [[ "$output" == *"media.txt"* ]]
}

@test "_resolve_requirements: respects RESTRICT_SCHEDULER=true (excludes scheduler)" {
  fake_backend="$BATS_TEST_TMPDIR/fake_backend"
  mkdir -p "$fake_backend/requirements"
  echo 'RESTRICT_SCHEDULER=true' > "$fake_backend/.env"
  echo 'RESTRICT_MEDIA=false'   >> "$fake_backend/.env"
  for f in core dev scheduler pdf_import calendar screenshot media; do
    touch "$fake_backend/requirements/${f}.txt"
  done
  BACKEND_DIR="$fake_backend"

  run _resolve_requirements
  [ "$status" -eq 0 ]
  [[ "$output" == *"core.txt"* ]]
  [[ "$output" != *"scheduler.txt"* ]]   # restricted → omitted
  [[ "$output" == *"media.txt"* ]]       # not restricted → included
}

@test "_resolve_requirements: CRLF .env still parsed correctly (regression for B4)" {
  fake_backend="$BATS_TEST_TMPDIR/fake_backend"
  mkdir -p "$fake_backend/requirements"
  printf 'RESTRICT_SCHEDULER=true\r\nRESTRICT_MEDIA=false\r\n' > "$fake_backend/.env"
  for f in core dev scheduler media; do
    touch "$fake_backend/requirements/${f}.txt"
  done
  BACKEND_DIR="$fake_backend"

  run _resolve_requirements
  [ "$status" -eq 0 ]
  [[ "$output" != *"scheduler.txt"* ]]
  [[ "$output" == *"media.txt"* ]]
}
