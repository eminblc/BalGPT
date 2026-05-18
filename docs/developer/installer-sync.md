# install.sh / lib Synchronization

Most backend code changes do **not** require touching `install.sh` or `lib/*.sh`. The installer is a thin orchestrator over `.env`, capability flags, requirements files, and systemd/Docker plumbing. Below is the canonical list of what triggers an installer update — keep these synchronized in the **same commit/PR** as the backend change, otherwise fresh installs will silently regress.

## 🟢 No installer change needed

These can ship without touching `install.sh` / `lib/`:

- New `/command` (`scripts/backend/guards/commands/`)
- New router or feature module (`scripts/backend/routers/`, `features/`)
- Refactor / bug fix in existing endpoints
- Bridge changes (`scripts/claude-code-bridge/server.js`)
- New unit tests (`scripts/tests/`)
- CLAUDE.md / docs / report updates
- SQLite schema migrations (handled at runtime by `sqlite_store`)

End-user runs `git pull && docker compose restart` (Docker) or `sudo systemctl restart personal-agent*` (native) — installer is not re-run.

## 🟡 Installer changes required

| Backend change | Installer files to update |
|---|---|
| New env variable in `config.py` | `scripts/backend/.env.example` (installer copies this; missing here = missing in user's `.env`) |
| New capability flag (`RESTRICT_*` or `*_ENABLED`) | `lib/capabilities.sh` (`cap_keys` + `cap_envs` arrays), `locales/install_{tr,en}.json` (`CAP_<KEY>` label), `scripts/backend/guards/capability_guard.py` (`register_capability_rule()` call) |
| Capability that needs its own Python packages | Also: create `scripts/backend/requirements/<name>.txt`, add to `lib/packages.sh` (`_PKG_CAP_KEYS` / `_PKG_ENV_VARS` / `_PKG_ACTIVE_VAL` arrays) |
| New LLM provider | `lib/wizard.sh` (Phase-2 LLM `case`), `locales/install_*.json` (`WIZ_LLM_<KEY>`, `TXT_L<N>` labels) |
| New messenger platform | `lib/wizard.sh` (Phase-1 messenger `case` and credential prompts), `locales/install_*.json` (`WIZ_MSG_<KEY>`, `TXT_M<N>` labels) |
| New webhook proxy option (e.g., Tailscale Funnel) | `lib/wizard.sh` (Phase-2 proxy `case`), `locales/install_*.json` (`WIZ_PRX_<KEY>`, `TXT_P<N>`) |
| New systemd service (3rd unit) | `systemd/<name>.service.template`, `lib/steps.sh` (`step_systemd` render + enable) |
| Docker compose service rename / port change | `docker-compose.yml` + `lib/steps.sh` (`step_docker_build` health-check URL, webhook auto-register polling) |
| Min Python or Node version bump | `install.sh` (`check_prereqs` version comparison), `README.md` + `README.tr.md` Prerequisites section |
| New user-facing wizard text | `locales/install_{tr,en}.json` (both languages — bats `every _S_* reference exists in both locales` test will fail otherwise) |

## 🔴 Coupled changes that require care

- **Renaming a `RESTRICT_*` flag**: search across `config.py`, `capability_guard.py`, `lib/capabilities.sh` (cap_envs), `lib/packages.sh` (_PKG_ENV_VARS), `.env.example`, `locales/install_*.json` — partial rename leaves stale `.env` keys after `--reconfigure-capabilities`.
- **Changing the systemd unit name** (`personal-agent.service`): break-change for any user with running deployments. Either don't, or ship a migration hook in `step_systemd`.
- **Removing a capability**: bump version comment in `.env.example` so `_caps_already_set` users get re-prompted on upgrade; remove from `lib/capabilities.sh` `cap_keys`/`cap_envs`; remove its `requirements/<name>.txt`.

## Safe vs Risky edits — how to keep sync work bug-free

The installer was deliberately built with **registry / data-driven patterns** so that 80% of sync work is **append-only**: you add a row to a table, you don't modify a function body. The danger zone is when you have to touch existing logic. Categorise your change before editing.

**🟢 Safe — append-only (~2% regression risk)**

These edits add a row to a registry; the surrounding function code is not modified. Bats + shellcheck catch the rest.

| Change | What you add |
|---|---|
| New env variable | A line at the bottom of `scripts/backend/.env.example`. Installer just `cp`s the file — no parsing involved. |
| New capability flag | A string each in `cap_keys` / `cap_envs` arrays (`lib/capabilities.sh`). Loop counts adjust automatically; runtime `cap_keys/cap_envs length mismatch` guard will hard-fail if you miscount. |
| New capability with packages | A row in `_PKG_CAP_KEYS`/`_PKG_ENV_VARS`/`_PKG_ACTIVE_VAL` (`lib/packages.sh`) + `scripts/backend/requirements/<name>.txt`. `_resolve_requirements` is fully data-driven. |
| New locale string | A `"KEY": "value"` pair in **both** `install_tr.json` and `install_en.json`. Bats `every _S_* reference exists in both locales` test catches asymmetry. |

**🟡 Medium — adds a branch to existing logic (~10% regression risk)**

You're modifying an existing `case` statement or a function with a fixed signature. Write a bats test for the new branch before merging.

| Change | What's at risk | Mitigation |
|---|---|---|
| New LLM provider (e.g., Mistral) | `lib/wizard.sh` Phase-2 `case` AND `_write_env`'s 24-positional-arg signature. Forgetting to wire the new args through `_apply_wiz_to_env` (Telegram bot path) leaves the .env partial. | Add a bats test that calls `_write_env` with the new provider's args; verify `.env` contains both old + new fields. |
| New messenger platform | **Two** wizards (`_wizard_whiptail` AND `_wizard_text`) need parallel branches — easy to update one and forget the other. | After editing whiptail flow, grep for the equivalent question in `_wizard_text`; both must end with the same `_write_env` call. |
| New webhook proxy option | `case` in Phase-2 + Docker auto-registration polling in `step_docker_build`. ngrok-specific URL detection may need re-thinking. | Test with `bash install.sh --docker --no-wizard` to skip the wizard but exercise the build path. |

**🔴 Risky — modifies existing function bodies (~25% regression risk)**

These touch validated, working code paths. Treat as a refactor: separate commit, fresh bats run before AND after, prefer hooks over rewrites.

| Change | Why it's risky | What to do instead |
|---|---|---|
| Bump min Python / Node version | `check_prereqs` version compare uses fragile `tr -d 'v' \| cut -d. -f1` — bumping past 9 → 10 boundary is a string-sort trap. | Replace the comparison with `printf '%s\n%s\n' "$current" "$min" \| sort -V \| head -1` instead of editing the existing line by hand. |
| Rename systemd unit | Any user with a running deployment breaks on next `git pull`. `systemctl disable old-name` not handled. | Don't rename. If you must, add a one-shot migration in `step_systemd` that detects the old unit and disables it before installing the new one. |
| Remove a capability | Old users have stale `RESTRICT_X=true/false` lines; `_caps_already_set` returns true and they never re-pick. | Bump a `# capability schema v=N` comment line in `.env.example`; have `_caps_already_set` compare versions, not just key existence. |
| Rename Docker compose service | Health-check polling URL + webhook auto-register URL break silently (curl returns 404, install.sh shows "Public URL bekleniyor" forever). | Update `docker-compose.yml`, `lib/steps.sh:step_docker_build` (search for service-name string literals), AND the README's troubleshooting tables in the same commit. |
| Refactor `_write_env`'s 24-arg signature | Every wizard, every messenger path, and `_apply_wiz_to_env` calls it positionally. | Convert to associative array (`declare -A` env_values) in **its own commit** with no other changes; bats tests should still pass; only THEN add the new field. |

## Practical rule of thumb

1. **Look at your diff**: if every line is a `+` (no `-`), you're in 🟢 territory — ship.
2. **If a `case` got a new branch but no existing branch was touched**: 🟡 — write one bats test for the new path.
3. **If you modified an existing function body**: 🔴 — re-run bats AND smoke test (`bash install.sh --no-wizard` + `--reconfigure-capabilities`) before merging.
4. **If you modified `_write_env`, `_load_strings`, `step_docker_build`, or `check_prereqs`**: treat as a refactor PR, not a feature PR — separate commit, code review, no other changes mixed in.

## Self-check before committing

Run all of these from the project root — they're cheap and catch most synchronization gaps:

```bash
# Bash syntax + shellcheck
bash -n install.sh && for f in lib/*.sh; do bash -n "$f"; done
shellcheck --severity=warning install.sh lib/*.sh

# Bats — locks in env helpers, capability resolution, locale parity
bats tests/install/

# Locale key parity (TR ↔ EN ↔ install.sh references)
python3 -c "
import json, re
src = open('install.sh').read() + ''.join(open(f).read() for f in __import__('glob').glob('lib/*.sh'))
refs = set(re.findall(r'_S_[A-Z][A-Z0-9_]*', src))
for lang in ('tr', 'en'):
    keys = {f'_S_{k}' for k in json.load(open(f'locales/install_{lang}.json'))}
    missing = refs - keys
    assert not missing, f'{lang}: missing keys {sorted(missing)}'
print('locale parity OK')
"

# Env example coverage (every config.py setting has a placeholder)
diff <(grep -oE '^[A-Z_]+=' scripts/backend/.env.example | sort -u) \
     <(grep -oE 'settings\.[a-z_][a-z0-9_]*' scripts/backend/**/*.py 2>/dev/null \
       | sed 's/settings\.//' | tr 'a-z' 'A-Z' | sort -u) || echo "(diff above shows missing keys in .env.example)"

# Bonus: make sure no new lib file forgot the source-block in install.sh
ls lib/*.sh | while read f; do
  grep -q "source \"\$ROOT_DIR/$f\"" install.sh || echo "WARNING: $f not sourced in install.sh"
done
```

CI runs `shellcheck` + `bats` jobs (see `.github/workflows/ci.yml`); the locale-parity bats test is the most likely to flag a forgotten translation.
