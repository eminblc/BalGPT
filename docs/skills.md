# Skills & Capabilities Reference

A complete inventory of every capability built into the personal AI agent — features, commands, adapters, guards, API endpoints, system requirements, and capability flags.

> **For contributors:** Update this file whenever a new skill is added, removed, or changed.

---

## Summary

| Category | Count |
|----------|-------|
| Feature Modules | 13 categories |
| `!command` System | 20 commands |
| LLM Adapters | 3 (Anthropic, Ollama, Gemini) |
| Messenger Adapters | 3 (WhatsApp, Telegram, CLI) |
| Guard Layer | 10 guards |
| `RESTRICT_*` Flags | 13 capability flags |

---

## 1. Feature Modules

### 1.1 Chat / Bridge Communication
**File:** `features/chat.py`  
**Feature code:** Core (FEAT-0)

| Function | Description |
|----------|-------------|
| `send_to_bridge(session_id, message, init_prompt, lang)` | Forwards message to Claude Code Bridge; 300 s timeout |
| `reset_bridge_session(session_id)` | Resets Bridge session |

**Dependencies:** `httpx`, Bridge `:8013`  
**Limitation:** Returns `bridge.timeout` or `bridge.unavailable` if the Bridge is unreachable.

---

### 1.2 Calendar
**File:** `features/calendar.py`  
**Feature code:** Core

| Function | Description |
|----------|-------------|
| `create_event(title, event_time, description, remind_before_minutes, recurring)` | Creates a calendar event |
| `list_upcoming(limit)` | Lists upcoming events |
| `delete_event(event_id)` | Deletes an event |
| `parse_datetime_from_text(text)` | NLP date parsing in Turkish / English (`dateparser`) |
| `check_and_notify_reminders(send_fn, lang)` | Fires due reminders |
| `format_event_list(events, lang)` | Formats event list for messaging |

**Dependencies:** `dateparser`, SQLite (`event_*` tables), `scheduler.py`  
**Restriction:** `RESTRICT_CALENDAR=true` blocks calendar-related messages.

---

### 1.3 Work Plans
**File:** `features/plans.py`  
**Feature code:** Core

| Function | Description |
|----------|-------------|
| `create_plan(title, description, priority, due_date, project_id)` | Creates a work plan (priority: 1=High, 2=Medium, 3=Low) |
| `list_plans(status)` | Lists plans (`"active"` or `"completed"`) |
| `complete_plan(plan_id)` | Marks a plan as completed |
| `delete_plan(plan_id)` | Deletes a plan |
| `format_plan_list(plans, lang)` | Formats plan list for messaging |

**Dependencies:** SQLite (`work_plans` table)  
**Restriction:** `RESTRICT_PLANS=true` blocks plan-related messages.

---

### 1.4 Scheduler
**File:** `features/scheduler.py`  
**Feature code:** FEAT-7, FEAT-9, FEAT-10

| Function | Description |
|----------|-------------|
| `create_one_shot_task(description, action_type, message, run_at)` | One-time scheduled task |
| `create_cron_task(description, action_type, message, cron_expr)` | Recurring cron task |
| `soft_delete_job(task_id)` | Soft-deletes a job |
| `apply_timezone(tz)` | Changes timezone at runtime (reconfigures APScheduler) |
| `get_current_timezone()` | Returns current active timezone |

**`action_type` values:**
- `send_message` → text is sent directly to the messenger
- `run_bridge` → prompt is forwarded to Bridge; Claude replies

**Dependencies:** `apscheduler`, SQLite (`scheduler.db`)  
**Restriction:** `RESTRICT_SCHEDULER=true` prevents APScheduler from starting at boot.

---

### 1.5 Project Management
**Files:** `features/projects.py`, `project_crud.py`, `project_service.py`, `project_scaffold.py`, `project_wizard.py`, `wizard_steps.py`, `wizard_core.py`  
**Feature code:** Core + FEAT-11

| Module | Function | Description |
|--------|----------|-------------|
| `project_crud.py` | `create_project`, `list_projects`, `get_project` | Project CRUD |
| `project_crud.py` | `start_beta_mode(project_id, session)` | Activates beta mode |
| `project_crud.py` | `update_active_context_project(project_id)` | Updates `data/active_context.json` |
| `project_service.py` | `start_project_services(project)` | Starts project services via tmux |
| `project_service.py` | `stop_project_services(project)` | Stops project services |
| `project_scaffold.py` | `_scaffold_project(project)` | Creates project directory structure and `CLAUDE.md` |
| `wizard_steps.py` | 8-step wizard | `ask_description` → `confirm_create` |

**Dependencies:** SQLite (`projects` table), `tmux`, `data/projects/`  
**Restriction:** `_UNSAFE_CMD_RE` — `>` and `&` characters are forbidden in service commands.  
**Restriction:** `RESTRICT_PROJECT_WIZARD=true` blocks project creation requests.

---

### 1.6 Conversation History
**File:** `features/history.py`  
**Feature code:** Core

| Function | Description |
|----------|-------------|
| `get_recent_messages(sender, limit)` | Returns last N messages |
| `get_session_summaries(sender, limit)` | Returns session summaries |
| `get_bridge_calls(sender, limit)` | Returns Bridge call history |
| `format_history(messages, lang)` | Formats message history for messaging |
| `format_summaries(summaries, lang)` | Formats session summaries for messaging |

**Dependencies:** SQLite (`messages`, `session_summaries`)  
**Restriction:** `RESTRICT_CONV_HISTORY=true` disables history recording.

---

### 1.7 Media Handler
**File:** `features/media_handler.py`  
**Feature code:** FEAT-1

| Function | Description |
|----------|-------------|
| `save_media(media_id, mime_type)` | Downloads WhatsApp media, saves to `data/media/YYYY-MM/` |
| `handle_image(sender, msg, session)` | Processes image message, forwards to Bridge |
| `handle_audio(sender, msg, session)` | Processes audio message |
| `handle_video(sender, msg, session)` | Processes video message |
| `handle_document(sender, msg, session)` | Processes document message (PDF triggers special flow) |

**Supported MIME types:** `image/jpeg`, `image/png`, `image/webp`, `audio/ogg`, `audio/mpeg`, `audio/mp4`, `video/mp4`, `application/pdf`  
**Dependencies:** `whatsapp/cloud_api.download_media`, `data/media/`  
**Restriction:** `RESTRICT_MEDIA=true` blocks all media messages.

---

### 1.8 PDF Importer
**File:** `features/pdf_importer.py`  
**Feature code:** Core

| Function | Description |
|----------|-------------|
| `import_from_whatsapp_media(media_id, sender, level, lang)` | WhatsApp PDF → text extraction → Bridge analysis → project scaffold |

**Flow:** WhatsApp media → PyMuPDF (max 30 pages) → Bridge analysis → `project_scaffold.py`  
**Dependencies:** `fitz` (PyMuPDF), `/tmp/personal-agent-pdf/`  
**Restriction:** `RESTRICT_PDF_IMPORT=true` blocks at feature-call level (even when media is enabled).

---

### 1.9 Webhook Proxy
**File:** `features/webhook_proxy.py`  
**Feature code:** PORT-6

| Function | Description |
|----------|-------------|
| `start_proxy(mode, port)` | Starts proxy; returns public URL |
| `get_public_url()` | Returns current public URL |

**Supported modes:**
- `ngrok` — tunnel via pyngrok (`NGROK_AUTHTOKEN` optional)
- `cloudflared` — tunnel via cloudflared CLI
- `external` — read from `PUBLIC_URL` env var
- `none` — no proxy

---

### 1.10 Terminal Execution
**File:** `features/terminal.py`  
**Feature code:** FEAT-12a

| Function | Description |
|----------|-------------|
| `execute_command(cmd_str, timeout, cwd)` | Executes shell command (`shell=True`); max 3500 chars output |
| `is_dangerous(cmd_str)` | Determines if command is flagged as dangerous |

**Dangerous command detection:** GUARDRAILS.md hint words + `_EXTRA_DANGEROUS` set (60+ tokens)  
**API endpoint:** `POST /internal/terminal` (localhost-only)  
**Restriction:** Dangerous commands require owner TOTP when invoked via `!terminal`.

---

### 1.11 Desktop Automation
**Files:** `desktop.py` (facade), `desktop_common.py`, `desktop_capture.py`, `desktop_input.py`, `desktop_vision.py`, `desktop_atspi.py`  
**Feature code:** FEAT-12, FEAT-8, FEAT-17  
**API endpoint:** `POST /internal/desktop` (localhost-only)  
**Requires:** `DESKTOP_ENABLED=true`

#### 1.11.1 Screen Capture (`desktop_capture.py`)
| Function | Description |
|----------|-------------|
| `capture_screen(output_path, region)` | Takes screenshot (`scrot` primary → ImageMagick fallback) |
| `ocr_screen()` | Screenshot + Tesseract OCR |
| `run_tesseract_on_file(image_path)` | OCR on an existing image file |

**System requirements:** `scrot`, `tesseract-ocr`, `tesseract-ocr-tur`, `DISPLAY=:0`  
**Note (FEAT-8):** `_detect_xauthority()` auto-locates `XAUTHORITY` (GDM → `~/.Xauthority` → empty); works even when launched from systemd without a display env.  
**Region support:** `(x, y, w, h)` captures only a portion of the screen.

#### 1.11.2 Keyboard / Mouse Input (`desktop_input.py`)
| Function | Description |
|----------|-------------|
| `xdotool_type(text, delay_ms)` | Types text into the active window (max 2000 chars; default 12 ms delay) |
| `xdotool_key(key)` | Sends a key or combination (e.g. `"ctrl+c"`, `"Return"`) |
| `xdotool_click(x, y, button)` | Mouse click at coordinates |
| `xdotool_move(x, y)` | Moves mouse to coordinates |
| `xdotool_scroll(direction, amount)` | Scroll wheel (up/down/left/right) |

**System requirements:** `xdotool`, X11 session

#### 1.11.3 Vision API (`desktop_vision.py`)
| Function | Description |
|----------|-------------|
| `vision_query(question, model, region, use_cache)` | Screenshot + Claude Vision API free-form question |
| `clear_bbox_cache()` | Clears bounding-box cache |
| `get_bbox_cache_stats()` | Returns cache statistics |

**Default model:** `claude-haiku-4-5-20251001`  
**Cache:** TTL 60 s; keyed by window title + question hash + region.

#### 1.11.4 System Operations (`desktop.py`)
| Function | Description |
|----------|-------------|
| `open_path(path)` | Opens file/folder with default app (`xdg-open`) |
| `unlock_screen()` | Unlocks screen (loginctl → xdg-screensaver → xdotool super) |
| `sudo_exec(cmd, timeout)` | Runs privileged command via `sudo -S` (`SYSTEM_PSSWRD` required) |
| `run_installer(path, timeout)` | Runs an installer (.deb, .exe, .msi, .sh, .AppImage, .rpm) |
| `get_windows()` | Lists open windows (wmctrl → xdotool fallback) |
| `focus_window(window_name, window_id)` | Brings window to front and focuses it |

**System requirements:** `xdg-utils`, `wmctrl`, `wine` (optional, for .exe/.msi)

#### 1.11.5 AT-SPI Accessibility (`desktop_atspi.py`)
| Function | Description |
|----------|-------------|
| `atspi_get_desktop_tree(max_depth)` | Returns accessibility tree as JSON |
| `atspi_find_element(role, name)` | Searches AT-SPI tree by role/name |
| `atspi_activate_element(role, name)` | Finds and activates (clicks/triggers) an AT-SPI element |

**Note:** AT-SPI queries run in a separate subprocess (SIGABRT risk). Requires `at-spi-bus-launcher` to be running.  
**Advantage:** Finds and clicks GUI elements without requiring Vision API calls.

#### 1.11.6 Media Send (`/internal/send_media`)
After a screenshot or screen recording, forward the file to the user:

```
POST /internal/send_media
{"path": "/tmp/wa_screenshot.png", "caption": "Screenshot"}
{"paths": ["/tmp/mon0.png", "/tmp/mon1.png"], "caption": "All monitors"}
```

MIME type is auto-detected from extension: `image/*` → photo, `video/*` → video, other → document.

---

### 1.12 Browser Automation
**File:** `features/browser.py`  
**Feature code:** FEAT-13, FEAT-15, FEAT-16  
**API endpoint:** `POST /internal/browser` (localhost-only)  
**Requires:** `BROWSER_ENABLED=true`

#### Core Actions
| Function | Description |
|----------|-------------|
| `browser_goto(url, session_id, headless, timeout, wait_until)` | Navigates to URL |
| `browser_fill(selector, value, session_id, ...)` | Fills input via CSS/XPath selector |
| `browser_click(selector, session_id, ...)` | Clicks an element |
| `browser_screenshot(session_id, full_page)` | Takes page screenshot (base64 PNG) |
| `browser_get_text(selector, session_id, ...)` | Returns element text content |
| `browser_get_content(session_id)` | Returns full page HTML |
| `browser_wait_for(selector, state, timeout, ...)` | Waits for element to reach a given state |
| `browser_eval(script, session_id)` | Executes JavaScript on the page |
| `browser_close(session_id)` | Closes a session |
| `browser_close_all()` | Closes all sessions (called at lifespan shutdown) |
| `browser_list_sessions()` | Lists open sessions |

#### Session Persistence (FEAT-15)
| Function | Description |
|----------|-------------|
| `browser_save_session(session_id)` | Saves cookies/localStorage to disk |
| `browser_delete_saved_session(session_id)` | Deletes saved disk state |
| `browser_list_saved_sessions()` | Lists saved sessions on disk |
| `browser_session_info(session_id)` | Returns session details (active, URL, title, saved) |

**Session management:** Independent Playwright context per `session_id`. Saved state auto-loads after restart — no re-login needed.  
**Dependencies:** `playwright`, Chromium  
**Restriction:** `BROWSER_ENABLED=false` returns 503. `BROWSER_HEADLESS=true` is the default.

---

### 1.13 Credential Store
**File:** `features/credential_store.py`  
**Feature code:** FEAT-16

| Function | Description |
|----------|-------------|
| `get_credential(site_slug, field)` | Returns `CREDENTIAL_<SITE_SLUG>_<FIELD>` env var value |
| `list_credentials()` | Lists defined credential site slugs |

**Security:** Password/token fields (`pass`, `password`, `secret`, `token`, `key`, `pin`) are masked as `***` in logs.  
**Usage:** Browser automation flows retrieve credentials with `get_credential("site", "user")`.

---

## 2. `!` Command System

**Location:** `guards/commands/` — registry-based (OCP)  
**Registration:** Each command calls `registry.register(Command())` in its own file.  
**Permission levels:** `Perm.OWNER`, `Perm.OWNER_TOTP`, `Perm.ADMIN`

| Command | File | Permission | Description |
|---------|------|-----------|-------------|
| `!help` | `help_cmd.py` | OWNER | Lists all commands |
| `!history` | `history_cmd.py` | OWNER | Shows recent message history |
| `!project` | `project_focus_cmd.py` | OWNER | Sets / shows active project |
| `!root-reset` | `root_reset_cmd.py` | OWNER | Resets Bridge session |
| `!restart` | `restart_cmd.py` | OWNER | Restarts services (math challenge + owner TOTP) |
| `!shutdown` | `shutdown_cmd.py` | OWNER | Stops FastAPI service (math challenge + owner TOTP) |
| `!schedule` | `schedule_cmd.py` | OWNER | Scheduled task management (list/delete/detail) |
| `!root-check` | `root_check_cmd.py` | OWNER | Shows last 5 lines of `root_actions.log` |
| `!beta` | `beta_exit.py` | OWNER | Exits project beta mode |
| `!project-delete` | `project_delete_cmd.py` | OWNER | Removes project from DB (math challenge + owner TOTP; filesystem untouched) |
| `!root-project` | `root_project_cmd.py` | OWNER | Assigns active project context to root agent |
| `!root-exit` | `root_exit_cmd.py` | OWNER | Exits root project context |
| `!cancel` | `cancel_cmd.py` | OWNER | Cancels active TOTP flow, pending action, or in-progress Bridge query |
| `!lang` | `lang_cmd.py` | OWNER | Changes interface language (tr/en); persisted to DB |
| `!model` | `model_cmd.py` | OWNER | Changes LLM model at runtime (persists until restart) |
| `!lock` | `lock_cmd.py` | OWNER | Locks the application (TOTP required); only `!unlock` works while locked |
| `!unlock` | `unlock_cmd.py` | OWNER | Unlocks the application (TOTP required); auto-locked at service start |
| `!terminal` | `terminal_cmd.py` | OWNER | Runs a shell command (dangerous commands require owner TOTP) |
| `!timezone` | `timezone_cmd.py` | OWNER | Changes timezone (IANA format; APScheduler is reconfigured) |

**Total:** 19 commands

---

## 3. Adapter Layer

### 3.1 LLM Adapters
**Location:** `adapters/llm/`  
**Factory:** `llm_factory.get_llm(backend)` — selected via `LLM_BACKEND` env var

| Provider | File | Env Variable | Notes |
|----------|------|-------------|-------|
| Anthropic | `anthropic_provider.py` | `ANTHROPIC_API_KEY` | Default |
| Ollama | `ollama_provider.py` | `OLLAMA_BASE_URL`, `OLLAMA_MODEL` | Local LLM |
| Gemini | `gemini_provider.py` | `GEMINI_API_KEY`, `GEMINI_MODEL` | Experimental |

**API:** `async complete(messages, model, max_tokens) -> str`  
**Multimodal:** Anthropic provider accepts list-format content for Vision queries.

### 3.2 Messenger Adapters
**Location:** `adapters/messenger/`  
**Factory:** `messenger_factory.get_messenger()` — singleton selected via `MESSENGER_TYPE` env var

| Messenger | File | Env Variable | Notes |
|-----------|------|-------------|-------|
| WhatsApp | `whatsapp_messenger.py` | Meta Cloud API credentials | Default |
| Telegram | `telegram_messenger.py` | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | Active |
| CLI | `cli_messenger.py` | — | Local testing; writes to stdout |

**API:** `send_text()`, `send_buttons()`, `send_image()`, `send_video()`

---

## 4. Guard Layer

**Location:** `guards/`  
**Architecture:** `GuardChain` → `[MessageGuard]` — each guard is evaluated in order

| Guard | File | Role |
|-------|------|------|
| `DeduplicationGuard` | `deduplication.py` | Prevents duplicate message processing |
| `BlacklistGuard` | `blacklist.py` | Blocked-sender check |
| `PermissionGuard` | `permission.py` | Owner / TOTP permission check |
| `RateLimiterGuard` | `rate_limiter.py` | Per-message rate limiting |
| `CapabilityGuard` | `capability_guard.py` | `RESTRICT_*` env flags — 13 capability categories |
| `SessionGuard` | `session.py` | In-memory session management; 24 h TTL |
| `RuntimeStateGuard` | `runtime_state.py` | Lock state check (`!lock` / `!unlock`) |
| `OutputFilter` | `output_filter.py` | Filters sensitive data from Bridge output |
| `ApiKeyGuard` | `api_key.py` | API key validation for `/agent/*` endpoints |
| `ApiRateLimiter` | `api_rate_limiter.py` | Per-API-endpoint rate limiting |

---

## 5. REST API Endpoints

### 5.1 Internal (localhost-only, no API key required)

| Endpoint | File | Description |
|----------|------|-------------|
| `POST /internal/desktop` | `desktop_router.py` | Desktop automation (17+ actions) |
| `POST /internal/browser` | `browser_router.py` | Browser automation (12+ actions) |
| `POST /internal/terminal` | `terminal_router.py` | Shell command execution |
| `POST /internal/send_media` | `internal_router.py` | Send a file (image/video/document) to the owner |
| `POST /internal/schedule` | `internal_router.py` | Create a scheduled task |
| `DELETE /internal/schedule/{id}` | `internal_router.py` | Delete a task |
| `GET /internal/schedules` | `internal_router.py` | List tasks |
| `PUT /internal/schedule/{id}` | `internal_router.py` | Update a task |
| `POST /internal/verify-admin-totp` | `internal_router.py` | Verify owner TOTP code (URL preserved for bridge compatibility) |

### 5.2 Agent API (`X-Api-Key` header required)

| Endpoint | File |
|----------|------|
| `GET/POST /agent/calendar` | `calendar_api.py` |
| `GET/POST /agent/plans` | `plans_api.py` |
| `GET/POST /agent/projects` | `projects_api.py` |
| `POST /agent/pdf-import` | `pdf_api.py` |
| `GET/POST /agent/schedules` | `scheduler_api.py` |

### 5.3 Webhooks

| Endpoint | File | Security |
|----------|------|---------|
| `POST /whatsapp/webhook` | `whatsapp_router.py` | HMAC-SHA256 |
| `GET /whatsapp/webhook` | `whatsapp_router.py` | Verify token |
| `POST /telegram/webhook` | `telegram_router.py` | `X-Telegram-Bot-Api-Secret-Token` |

---

## 6. Capability Flags (`RESTRICT_*`)

All flags default to `false` (feature active). Set to `true` to restrict.

| Env Flag | Level | What it restricts |
|----------|-------|-------------------|
| `RESTRICT_FS_OUTSIDE_ROOT` | Message (regex) | Filesystem access outside project root |
| `RESTRICT_NETWORK` | Message (regex) | External network / HTTP requests |
| `RESTRICT_SHELL` | Message (regex) | Shell command execution |
| `RESTRICT_SERVICE_MGMT` | Message (regex) | Service management (systemd/tmux) |
| `RESTRICT_MEDIA` | Message (msg_type) | Media messages (image/video/document/audio) |
| `RESTRICT_CALENDAR` | Message (regex) | Calendar and scheduled task messages |
| `RESTRICT_PROJECT_WIZARD` | Message (regex) | Project creation wizard |
| `RESTRICT_SCREENSHOT` | Message (regex) | Headless browser / screenshot requests |
| `RESTRICT_SCHEDULER` | Startup | APScheduler subsystem — won't start at boot |
| `RESTRICT_PDF_IMPORT` | Feature-call | PDF import pipeline |
| `RESTRICT_CONV_HISTORY` | Router-call | Conversation history recording (privacy) |
| `RESTRICT_PLANS` | Message (regex) | Work plan management (`!plan` commands) |
| `RESTRICT_INTENT_CLASSIFIER` | Feature-call | LLM intent detection (saves one API call per message) |

To add a new restriction: `capability_guard.register_capability_rule()` + bool field in `config.py` + comment in `.env.example` + entry in `install.sh` `cap_keys`/`cap_envs` arrays + keys in both locale files.

---

## 7. System Requirements by Skill

| Skill | System Package | Python Package |
|-------|---------------|---------------|
| Screen Capture | `scrot`, `tesseract-ocr`, `tesseract-ocr-tur` | — |
| Keyboard / Mouse | `xdotool` | — |
| Window Management | `wmctrl` | — |
| Desktop (general) | `xdg-utils` | — |
| Browser Automation | Chromium | `playwright` |
| AT-SPI Accessibility | `at-spi2-core` | `pyatspi` (optional) |
| PDF Import | — | `fitz` (PyMuPDF) |
| NLP Date Parsing | — | `dateparser` |
| Wine (.exe support) | `wine` (optional) | — |
| Webhook Proxy | — | `pyngrok` (optional) |

Install all desktop automation dependencies at once:
```bash
sudo apt install scrot tesseract-ocr tesseract-ocr-tur xdg-utils xdotool wmctrl at-spi2-core
```

---

## 8. Known Limitations

| ID | Area | Description |
|----|------|-------------|
| BUG-M2 | `telegram_router.py` | `restrict_conv_history` guard missing (present in WhatsApp router, absent in Telegram) |
| LOG-1 | Logging | Console output written twice |
| LOG-4 | Logging | No dedicated `security.log` channel for security events |
