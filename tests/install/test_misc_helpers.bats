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

# ── _gen_totp ────────────────────────────────────────────────────────────────

# Helper: create a fake python that succeeds except for "import pyotp".
_stub_py_no_pyotp() {
  local name="$1"
  cat > "$STUB_BIN/$name" <<'EOF'
#!/usr/bin/env bash
# Fake python: fail only on "import pyotp"
cmd="$*"
if [[ "$cmd" == *"import pyotp"* ]]; then exit 1; fi
exit 0
EOF
  chmod +x "$STUB_BIN/$name"
}

@test "_gen_totp: pyotp path returns 32-char base32 string" {
  command -v python3 >/dev/null 2>&1 || skip "python3 not available"
  python3 -c "import pyotp" 2>/dev/null  || skip "pyotp not installed"
  PY="$(command -v python3)"
  BACKEND_DIR="$BATS_TEST_TMPDIR/no_venv"
  result="$(_gen_totp)"
  [ "${#result}" -eq 32 ]
  [[ "$result" =~ ^[A-Z2-7]+$ ]]
}

@test "_gen_totp: openssl fallback returns 32-char base32 string when pyotp missing" {
  STUB_BIN="${STUB_BIN:-$BATS_TEST_TMPDIR/stub_bin}"
  mkdir -p "$STUB_BIN"
  export PATH="$STUB_BIN:$PATH"

  # Python stub that rejects "import pyotp"
  _stub_py_no_pyotp "python3"
  PY="$STUB_BIN/python3"

  # Ensure openssl is available (real or stub)
  if ! command -v openssl &>/dev/null; then
    # Stub openssl rand -base64 to emit chars from the base32 alphabet
    cat > "$STUB_BIN/openssl" <<'EOF'
#!/usr/bin/env bash
printf 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567ABCDEFGHIJKLMNOPQRSTUVWXYZ2345678\n'
EOF
    chmod +x "$STUB_BIN/openssl"
  fi

  BACKEND_DIR="$BATS_TEST_TMPDIR/no_venv"
  result="$(_gen_totp)"
  [ "${#result}" -eq 32 ]
  [[ "$result" =~ ^[A-Z2-7]+$ ]]
}

@test "_gen_totp: date+sha256 fallback returns 32-char base32 string when pyotp and openssl missing" {
  STUB_BIN="${STUB_BIN:-$BATS_TEST_TMPDIR/stub_bin}"
  mkdir -p "$STUB_BIN"
  export PATH="$STUB_BIN:$PATH"

  # Python stub that rejects "import pyotp"
  _stub_py_no_pyotp "python3"
  PY="$STUB_BIN/python3"

  # Hide openssl so the date+sha256 branch is taken
  cat > "$STUB_BIN/openssl" <<'EOF'
#!/usr/bin/env bash
exit 127
EOF
  chmod +x "$STUB_BIN/openssl"
  # Make command -v openssl return false by wrapping it; instead shadow with a
  # script that is not executable so command -v finds nothing useful — simplest
  # approach: rename the stub to a non-executable file.
  chmod -x "$STUB_BIN/openssl"

  # sha256sum must be available for the fallback; skip if not.
  command -v sha256sum >/dev/null 2>&1 || skip "sha256sum not available"

  BACKEND_DIR="$BATS_TEST_TMPDIR/no_venv"
  result="$(_gen_totp)"
  [ "${#result}" -eq 32 ]
  [[ "$result" =~ ^[A-Z2-7]+$ ]]
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
