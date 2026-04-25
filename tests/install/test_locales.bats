#!/usr/bin/env bats
# Tests for the JSON-based i18n loader (_load_strings).  Locks in the
# guarantee that every _S_* key referenced by install.sh is present in
# both locale files.

setup() {
  ROOT_DIR="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"
  export ROOT_DIR
  # Every test in this file depends on python3 (the loader uses it,
  # the sanity checks use it).  Skip the whole file gracefully on
  # python-less containers.
  command -v python3 >/dev/null 2>&1 || skip "python3 not available"
}

@test "locales/install_tr.json exists and is valid JSON" {
  [ -f "$ROOT_DIR/locales/install_tr.json" ]
  python3 -c "import json; json.load(open('$ROOT_DIR/locales/install_tr.json'))"
}

@test "locales/install_en.json exists and is valid JSON" {
  [ -f "$ROOT_DIR/locales/install_en.json" ]
  python3 -c "import json; json.load(open('$ROOT_DIR/locales/install_en.json'))"
}

@test "TR and EN locales have identical keys" {
  python3 -c "
import json
tr = set(json.load(open('$ROOT_DIR/locales/install_tr.json')))
en = set(json.load(open('$ROOT_DIR/locales/install_en.json')))
diff = tr ^ en
assert not diff, f'Key mismatch: {sorted(diff)}'
"
}

@test "_load_strings: loads EN and sets _S_BANNER_TITLE" {
  # shellcheck source=/dev/null
  source "$ROOT_DIR/install.sh"
  INSTALL_LANG=en _load_strings
  [ "$_S_BANNER_TITLE" = "BalGPT — Setup" ]
}

@test "_load_strings: loads TR and sets _S_BANNER_TITLE" {
  # shellcheck source=/dev/null
  source "$ROOT_DIR/install.sh"
  INSTALL_LANG=tr _load_strings
  [ "$_S_BANNER_TITLE" = "BalGPT — Kurulum" ]
}

@test "_load_strings: falls back to TR on unknown language" {
  # shellcheck source=/dev/null
  source "$ROOT_DIR/install.sh"
  INSTALL_LANG=xx _load_strings
  # Falls back to install_tr.json
  [ "$_S_BANNER_TITLE" = "BalGPT — Kurulum" ]
}

@test "every _S_* reference in install.sh exists in both locales" {
  python3 - <<PYEOF
import json, re
src = open("$ROOT_DIR/install.sh").read()
refs = set(re.findall(r'_S_[A-Z][A-Z0-9_]*', src))
for lang in ("tr", "en"):
    keys = {f"_S_{k}" for k in json.load(open(f"$ROOT_DIR/locales/install_{lang}.json"))}
    missing = refs - keys
    assert not missing, f"{lang}: missing {sorted(missing)}"
PYEOF
}
