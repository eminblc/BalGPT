# Contributing

Thank you for your interest in contributing to this project!

## Before You Start

- This is a **single-user personal agent** — changes must not break the owner's remote access chain (`!restart` command).
- Read `CLAUDE.md` for architecture decisions and critical constraints.
- Read `GUARDRAILS.md` for the list of prohibited operations.

## Development Setup

```bash
git clone https://github.com/<your-fork>/99-root.git
cd 99-root

# Python dependencies
cd scripts/backend && python -m venv venv
venv/bin/pip install -r requirements.txt

# Node dependencies
cd ../claude-code-bridge && npm install

# Copy and fill in environment variables
cp scripts/backend/.env.example scripts/backend/.env
```

Run locally (without systemd):

```bash
cd scripts
backend/venv/bin/uvicorn backend.main:app --host 0.0.0.0 --port 8010

# In a separate terminal:
cd scripts/claude-code-bridge && node server.js
```

Health check:

```bash
curl -s http://localhost:8010/health
curl -s http://localhost:8013/health
```

## Code Style

- **Python:** Follow existing patterns — async/await, type hints, `logging` module (no `print`).
- **Imports:** Absolute within the package (`from ..config import settings`).
- **No new `os.environ` calls** — all settings go through `config.py` → `Settings` class.
- **No circular imports** — dependency direction: `Router → Guards → Features → Store`.

## Syntax Check (required before PR)

```bash
# Python
cd scripts && backend/venv/bin/python -c "from backend.main import app; print('OK')"

# Node
node --check scripts/claude-code-bridge/server.js
```

## Adding a New `!command`

1. Create `scripts/backend/guards/commands/my_cmd.py`
2. Implement the `Command` Protocol (`cmd_id`, `async execute(sender, arg, session)`)
3. Define `perm = Perm.OWNER` (or appropriate level) as a class attribute — `required_perm()` reads this from the registry; if missing, the command returns "no permission"
4. Call `registry.register(MyCommand())` at the bottom of the file
5. Add an import line to `guards/commands/__init__.py`
6. Do **not** touch `main.py`, `guards/permission.py`, or any other existing file

## Localization (i18n)

All user-facing strings must use the `t()` helper — never hard-code Turkish or English text.

1. Add your key to both `locales/tr.json` and `locales/en.json` under the appropriate namespace
2. Import in your module: `from ..i18n import t`
3. Use it: `t("namespace.key", lang, **kwargs)` — `lang` comes from `session.get("lang", "tr")`
4. Interpolation variables use `{name}` syntax in the JSON values

## Adding a New LLM Backend

1. Create `scripts/backend/adapters/llm/myprovider_provider.py`
2. Implement `GeminiProvider`-style class with `async complete(messages, model, max_tokens) -> str`
3. Add `elif resolved == "myprovider":` in `llm_factory.py`
4. Add settings to `config.py` and `.env.example`

## Adding a New Messenger Platform

1. Create `scripts/backend/adapters/messenger/myplatform_messenger.py`
2. Implement `AbstractMessenger` Protocol (`send_text`, `send_buttons`, `receive_message`)
3. Update `messenger_factory.py`

## Pull Request Guidelines

- **One concern per PR** — don't mix refactoring with new features.
- **CI must pass** — Python syntax check + Node syntax check run automatically.
- **Security-sensitive files** — changes to `whatsapp_router.py`, `cloud_api.py`, `guards/__init__.py`, or `restart_cmd.py` require a note explaining how the `!restart` chain is unaffected.
- **No `.env` files** — never commit secrets; the CI workflow will reject them.

## Reporting Issues

Use the issue templates:
- **Bug report** — unexpected behavior, crashes, incorrect output
- **Feature request** — new capability or integration

## License

By contributing, you agree that your changes will be licensed under the [MIT License](LICENSE).
