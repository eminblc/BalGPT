#!/usr/bin/env bats
# Tests for critical install steps: step_systemd, step_pm2, step_docker_build.
# Commands that would touch real infrastructure (systemctl, pm2, docker) are
# replaced with stub scripts placed on a private PATH prefix so the real system
# is never modified.

setup() {
  ROOT_DIR="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"
  export ROOT_DIR

  # ── Stub bin directory ──────────────────────────────────────────────────────
  # All fake executables live here; prepend so they shadow real commands.
  STUB_BIN="$BATS_TEST_TMPDIR/stub_bin"
  mkdir -p "$STUB_BIN"
  export PATH="$STUB_BIN:$PATH"

  # Fake .env and requirements for _resolve_requirements (used by docker_build)
  FAKE_BACKEND="$BATS_TEST_TMPDIR/fake_backend"
  mkdir -p "$FAKE_BACKEND/requirements"
  touch "$FAKE_BACKEND/.env"
  for cap in core dev; do
    touch "$FAKE_BACKEND/requirements/${cap}.txt"
  done

  # Provide a fake HOME so step_docker_build's ~/.claude check is isolated
  FAKE_HOME="$BATS_TEST_TMPDIR/fake_home"
  mkdir -p "$FAKE_HOME/.claude"
  printf '{"oauth":{"token":"fake"}}' > "$FAKE_HOME/.claude/.credentials.json"

  # Source install.sh (sets NO_SYSTEMD, USE_PM2, etc.) with sane defaults.
  # set -euo pipefail is active inside install.sh; source it in a sub-context
  # so a sourced `die` (exit 1) doesn't abort bats.  We re-source as needed.
  INSTALL_LANG=tr \
    NO_SYSTEMD=false \
    USE_PM2=false \
    USE_DOCKER=false \
    BACKEND_DIR="$FAKE_BACKEND" \
    HOME="$FAKE_HOME" \
    source "$ROOT_DIR/install.sh" 2>/dev/null || true
  INSTALL_LANG=tr _load_strings 2>/dev/null || true

  # Override BACKEND_DIR / HOME after source so all helpers see them too
  BACKEND_DIR="$FAKE_BACKEND"
  export BACKEND_DIR HOME="$FAKE_HOME"
}

# ── Helper: create a stub command that exits 0 and optionally prints output ──
_stub() {
  local name="$1" body="${2:-}"
  printf '#!/usr/bin/env bash\n%s\n' "$body" > "$STUB_BIN/$name"
  chmod +x "$STUB_BIN/$name"
}

# ── Helper: remove a stub so the real command (or no command) is found ───────
_remove_stub() {
  rm -f "$STUB_BIN/$1"
}

# ═══════════════════════════════════════════════════════════════════════════════
# step_systemd
# ═══════════════════════════════════════════════════════════════════════════════

@test "step_systemd: skips when NO_SYSTEMD=true" {
  NO_SYSTEMD=true
  run step_systemd
  [ "$status" -eq 0 ]
  # Should print the skip message and NOT attempt render_template
  [[ "$output" == *"$_S_STEP_SYSTEMD_SKIP"* ]]
}

@test "step_systemd: warns and returns when systemctl is not on PATH" {
  NO_SYSTEMD=false
  # Ensure systemctl is not found (remove stub if any, hide real one)
  _remove_stub systemctl
  local _saved_path="$PATH"
  # Strip any real systemctl from PATH by wrapping command -v
  PATH="$STUB_BIN"  # minimal PATH without systemd dirs

  run step_systemd
  [ "$status" -eq 0 ]
  [[ "$output" == *"$_S_STEP_SYSTEMD_MISSING"* ]]

  PATH="$_saved_path"
}

@test "step_systemd: renders service files with correct placeholder substitution" {
  # Only exercise render_template — does not require systemctl.
  local tpl="$BATS_TEST_TMPDIR/test.service.template"
  local out="$BATS_TEST_TMPDIR/test.service"
  printf '[Service]\nUser={{USER}}\nWorkingDir={{ROOT_DIR}}\nExecStart={{NODE_PATH}} server.js\nPort={{API_PORT}} {{BRIDGE_PORT}}\n' > "$tpl"

  CURRENT_USER="testuser"
  NODE_PATH="/usr/local/bin/node"
  API_PORT="8010"
  BRIDGE_PORT="8013"

  render_template "$tpl" "$out"

  grep -q "User=testuser"            "$out"
  grep -q "WorkingDir=$ROOT_DIR"     "$out"
  grep -q "ExecStart=/usr/local/bin/node" "$out"
  grep -q "Port=8010 8013"           "$out"
  # No leftover placeholders
  ! grep -q '{{' "$out"
}

# ═══════════════════════════════════════════════════════════════════════════════
# step_pm2
# ═══════════════════════════════════════════════════════════════════════════════

@test "step_pm2: returns immediately when USE_PM2=false" {
  USE_PM2=false
  # Record whether pm2/npm are called by tracking a sentinel file
  _stub pm2  "touch '$BATS_TEST_TMPDIR/pm2_called'"
  _stub npm  "touch '$BATS_TEST_TMPDIR/npm_called'"

  run step_pm2
  [ "$status" -eq 0 ]
  # Neither pm2 nor npm should have been invoked
  [ ! -f "$BATS_TEST_TMPDIR/pm2_called" ]
  [ ! -f "$BATS_TEST_TMPDIR/npm_called" ]
}

@test "step_pm2: skips npm install when pm2 already exists" {
  USE_PM2=true
  # pm2 exists — returns version, and records calls
  _stub pm2 "
case \"\$1\" in
  --version) echo '5.3.0' ;;
  start)     touch '$BATS_TEST_TMPDIR/pm2_start_called' ;;
  save)      : ;;
  startup)   : ;;
esac"
  _stub npm "touch '$BATS_TEST_TMPDIR/npm_global_called'"

  run step_pm2
  [ "$status" -eq 0 ]
  # pm2 was called for start
  [ -f "$BATS_TEST_TMPDIR/pm2_start_called" ]
  # npm -g install should NOT have been called
  [ ! -f "$BATS_TEST_TMPDIR/npm_global_called" ]
  [[ "$output" == *"$_S_STEP_PM2_EXISTS"* ]]
}

@test "step_pm2: installs pm2 via npm when pm2 is missing" {
  USE_PM2=true
  _remove_stub pm2

  # Provide npm stub; after install, a pm2 stub appears
  _stub npm "
if [[ \"\$*\" == *'install'* && \"\$*\" == *'-g'* ]]; then
  # Simulate npm installing pm2 by creating the pm2 stub
  printf '#!/usr/bin/env bash\ncase \"\$1\" in\n  --version) echo 5.3.0 ;;\n  start) : ;;\n  save) : ;;\n  startup) : ;;\nesac\n' > '$STUB_BIN/pm2'
  chmod +x '$STUB_BIN/pm2'
fi"

  run step_pm2
  [ "$status" -eq 0 ]
  [[ "$output" == *"$_S_STEP_PM2_INSTALLED"* ]]
}

# ═══════════════════════════════════════════════════════════════════════════════
# step_docker_build
# ═══════════════════════════════════════════════════════════════════════════════

# Helper: temporarily redirect die() to stdout so `run` can capture the message.
# die() normally writes to stderr (log.sh: `echo "[✗] $*" >&2; exit 1`), which
# bats does not capture in $output by default.
_die_to_stdout() { die() { echo "[✗] $*"; exit 1; }; }

# Helper: set up a minimal fake ROOT_DIR so step_docker_build can read
# HOST_FS_ACCESS from scripts/backend/.env and write docker-compose.override.yml.
_setup_fake_root() {
  local hfs_value="$1"
  FAKE_ROOT="$BATS_TEST_TMPDIR/fake_root"
  mkdir -p "$FAKE_ROOT/scripts/backend/requirements"
  echo "HOST_FS_ACCESS=${hfs_value}" > "$FAKE_ROOT/scripts/backend/.env"
  for cap in core dev; do touch "$FAKE_ROOT/scripts/backend/requirements/${cap}.txt"; done
  BACKEND_DIR="$FAKE_ROOT/scripts/backend"
  ROOT_DIR="$FAKE_ROOT"
  export BACKEND_DIR ROOT_DIR
}

# Full docker stub: succeeds for info, compose version, compose build, compose up.
_stub_docker_ok() {
  _stub docker "
case \"\$1\" in
  info)    : ;;
  compose)
    shift
    case \"\$1\" in
      version) echo 'Docker Compose v2.0' ;;
      *)       : ;;   # build / up / etc. → success
    esac ;;
esac"
}

@test "step_docker_build: exits non-zero when docker command is not found" {
  _remove_stub docker
  _die_to_stdout

  run step_docker_build
  [ "$status" -ne 0 ]
}

@test "step_docker_build: error message mentions docker when docker is not found" {
  _remove_stub docker
  _die_to_stdout

  run step_docker_build
  [[ "$output" == *"docker"* ]]
}

@test "step_docker_build: exits non-zero when docker compose is unavailable" {
  _stub docker "
case \"\$1\" in
  info)    : ;;
  compose) exit 1 ;;
esac"
  _die_to_stdout

  run step_docker_build
  [ "$status" -ne 0 ]
}

@test "step_docker_build: generates override.yml with rw mount for HOST_FS_ACCESS=rw" {
  _setup_fake_root rw
  _stub_docker_ok

  step_docker_build || true
  local override="$FAKE_ROOT/docker-compose.override.yml"
  [ -f "$override" ]
  grep -q '/:/app/host_root:rw' "$override"
  ! grep -q '/:/app/host_root:ro' "$override"
}

@test "step_docker_build: generates override.yml with ro mount for HOST_FS_ACCESS=ro" {
  _setup_fake_root ro
  _stub_docker_ok

  step_docker_build || true
  local override="$FAKE_ROOT/docker-compose.override.yml"
  [ -f "$override" ]
  grep -q '/:/app/host_root:ro' "$override"
  ! grep -q '/:/app/host_root:rw' "$override"
}

@test "step_docker_build: generates override.yml without volume section for HOST_FS_ACCESS=none" {
  _setup_fake_root none
  _stub_docker_ok

  step_docker_build || true
  local override="$FAKE_ROOT/docker-compose.override.yml"
  [ -f "$override" ]
  ! grep -q 'host_root' "$override"
  ! grep -q 'volumes:' "$override"
}
