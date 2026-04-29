#!/usr/bin/env bats
# Tests for .env reader/writer helpers in install.sh.  These are the
# most bug-prone functions (CRLF parsing, sed delimiter clashes, missing
# keys) so they get the most coverage.

setup() {
  # Resolve repo root regardless of where bats is invoked from
  ROOT_DIR="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"
  export ROOT_DIR
  # shellcheck source=/dev/null
  source "$ROOT_DIR/install.sh"

  # Per-test scratch .env file
  ENV_FILE="$BATS_TEST_TMPDIR/test.env"
  : > "$ENV_FILE"
}

# ── _read_env_var ────────────────────────────────────────────────────────────

@test "_read_env_var: reads a basic value" {
  echo 'FOO=hello' > "$ENV_FILE"
  result="$(_read_env_var FOO "$ENV_FILE")"
  [ "$result" = "hello" ]
}

@test "_read_env_var: strips surrounding double quotes" {
  echo 'FOO="quoted-value"' > "$ENV_FILE"
  result="$(_read_env_var FOO "$ENV_FILE")"
  [ "$result" = "quoted-value" ]
}

@test "_read_env_var: strips trailing carriage return (CRLF .env)" {
  printf 'FOO=value\r\n' > "$ENV_FILE"
  result="$(_read_env_var FOO "$ENV_FILE")"
  [ "$result" = "value" ]
  # Length must be exactly 5, not 6 (would include \r)
  [ "${#result}" = "5" ]
}

@test "_read_env_var: returns empty for missing key" {
  echo 'OTHER=x' > "$ENV_FILE"
  result="$(_read_env_var MISSING "$ENV_FILE")"
  [ -z "$result" ]
}

@test "_read_env_var: returns empty for missing file" {
  result="$(_read_env_var FOO /nonexistent/path.env)"
  [ -z "$result" ]
}

@test "_read_env_var: preserves '=' inside value" {
  echo 'TOKEN=a=b=c' > "$ENV_FILE"
  result="$(_read_env_var TOKEN "$ENV_FILE")"
  [ "$result" = "a=b=c" ]
}

@test "_read_env_var: returns first match when key duplicated" {
  printf 'FOO=first\nFOO=second\n' > "$ENV_FILE"
  result="$(_read_env_var FOO "$ENV_FILE")"
  [ "$result" = "first" ]
}

# ── _env_set ─────────────────────────────────────────────────────────────────

@test "_env_set: inserts a new key" {
  _env_set FOO "bar" "$ENV_FILE"
  result="$(_read_env_var FOO "$ENV_FILE")"
  [ "$result" = "bar" ]
}

@test "_env_set: updates an existing key in-place" {
  echo 'FOO=old' > "$ENV_FILE"
  _env_set FOO "new" "$ENV_FILE"
  result="$(_read_env_var FOO "$ENV_FILE")"
  [ "$result" = "new" ]
  # File should still have exactly one line
  [ "$(wc -l < "$ENV_FILE")" = "1" ]
}

@test "_env_set: preserves other keys" {
  printf 'A=1\nB=2\nC=3\n' > "$ENV_FILE"
  _env_set B "updated" "$ENV_FILE"
  [ "$(_read_env_var A "$ENV_FILE")" = "1" ]
  [ "$(_read_env_var B "$ENV_FILE")" = "updated" ]
  [ "$(_read_env_var C "$ENV_FILE")" = "3" ]
}

@test "_env_set: handles values with '@' and '/' (sed delimiter clash)" {
  _env_set URL "https://user@example.com/path" "$ENV_FILE"
  result="$(_read_env_var URL "$ENV_FILE")"
  [ "$result" = "https://user@example.com/path" ]
}

@test "_env_set: handles values with backslash" {
  _env_set REGEX 'a\b\c' "$ENV_FILE"
  result="$(_read_env_var REGEX "$ENV_FILE")"
  [ "$result" = 'a\b\c' ]
}

# ── _env_comment_out / _env_uncomment ────────────────────────────────────────

@test "_env_comment_out: comments an active line" {
  echo 'FOO=bar' > "$ENV_FILE"
  _env_comment_out FOO "$ENV_FILE"
  grep -q '^# FOO=bar$' "$ENV_FILE"
}

@test "_env_comment_out: no-op when key absent" {
  echo 'OTHER=x' > "$ENV_FILE"
  _env_comment_out MISSING "$ENV_FILE"
  # File unchanged
  [ "$(cat "$ENV_FILE")" = "OTHER=x" ]
}

@test "_env_uncomment: restores a commented line" {
  echo '# FOO=bar' > "$ENV_FILE"
  _env_uncomment FOO "$ENV_FILE"
  grep -q '^FOO=bar$' "$ENV_FILE"
}

@test "_env_comment_out then _env_uncomment is a round-trip" {
  echo 'FOO=baz' > "$ENV_FILE"
  _env_comment_out FOO "$ENV_FILE"
  _env_uncomment   FOO "$ENV_FILE"
  [ "$(cat "$ENV_FILE")" = "FOO=baz" ]
}
