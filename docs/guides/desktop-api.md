# Desktop API (Usage from Bridge) ⚠️ BETA

> **This feature is in beta.** Desktop automation may not work as expected in every environment and scenario. Coordinate errors, window focus issues, or actions producing unintended results are possible.

Use this endpoint when the user requests desktop automation, screen control, or GUI operations:

**IMPORTANT:** Can only be called from localhost. No API key required. All actions are rejected if `DESKTOP_ENABLED=false`.

## Desktop TOTP Flow (DESK-TOTP-2 — Server-Side)

The desktop endpoint (`/internal/desktop` and `/internal/desktop/batch`) may **only be used for a desktop task explicitly requested by the user in this turn**. Do not make desktop calls spontaneously, "to be helpful", in the background, or as a side effect of another operation.

**TOTP management is now server-side — LLM not involved:**

- When a desktop action is needed, call `/internal/desktop` directly. Do not send the `code` field.
- If the gate is locked, the server automatically requests TOTP from the user via WhatsApp. You receive `{"ok": false, "requires_totp": true}` in response.
- If you receive this response, tell the user: `"The server has sent a TOTP request to unlock the desktop. Please try again after entering the code."` — do nothing else, do not ask for TOTP.
- When the gate is open (no `requires_totp`), execute actions directly.

**Forbidden:**
- Calling `/internal/desktop*` when the user has not requested a desktop operation.
- Asking the user for TOTP — this is the server's responsibility.
- Adding the `code` field to the request body — server verification is done via WhatsApp.

## Running actions
```
POST http://localhost:8010/internal/desktop
Content-Type: application/json
{"action": "unlock_screen"}
{"action": "is_locked"}
{"action": "check_vision"}
{"action": "sudo_exec", "sudo_cmd": ["apt", "install", "-y", "scrot"], "timeout": 60}
{"action": "run", "target": "/tmp/setup.deb", "timeout": 120}
{"action": "type", "text": "<text_to_type>", "window_id": "0x05000003", "delay_ms": 12}
{"action": "key", "key": "ctrl+c"}
{"action": "click", "x": 500, "y": 300, "button": 1}
{"action": "screenshot", "ocr": false}
{"action": "vision_query", "question": "What does the screen say?"}
{"action": "get_windows"}
{"action": "focus_window", "window_name": "Firefox"}
```

## Supported actions

| Action | Description | Required fields |
|--------|-------------|-----------------|
| `unlock_screen` | Unlock screen (loginctl → xdg-screensaver → xdotool super) + verification + DPMS wake | — |
| `is_locked` | Check if screen is locked (returns `{"locked": true/false}`) | — |
| `check_vision` | Check Vision API availability; suggests Playwright fallback if `available=false` | — |
| `sudo_exec` | Run privileged command with `sudo -S` (`SYSTEM_PSSWRD` required) | `sudo_cmd: list[str]` |
| `open` | Open file/folder with default application (xdg-open) | `target` |
| `run` | Run an installer file (.deb, .exe, .msi, .sh, .AppImage, .rpm) | `target` |
| `screenshot` | Take screenshot; also includes OCR text if `ocr=true` | — |
| `ocr` | Screenshot + tesseract OCR (text only) | — |
| `type` | Type text into the active window (xdotool type) | `text` |
| `key` | Send key/combination (xdotool key) | `key` |
| `click` | Mouse click at coordinate (xdotool) | `x`, `y` |
| `move` | Move mouse to coordinate (xdotool) | `x`, `y` |
| `scroll` | Mouse wheel scroll | `direction` (up/down/left/right) |
| `vision_query` | Screenshot + free question via Claude Vision API | `question` |
| `get_windows` | List open windows (wmctrl/xdotool) | — |
| `focus_window` | Bring window to front and focus | `window_id` or `window_name` |

## Response format
- Success: `{"ok": true, "message": "✅ ...", "text": "..."}` (text: OCR/vision)
- Error: `{"ok": false, "message": "❌ error description"}`
- `sudo_exec`: `{"ok": true/false, "message": "...", "returncode": 0}`

## Security notes
- `SYSTEM_PSSWRD` — `SecretStr`; not written to logs; used with `.get_secret_value()`
- `sudo_exec` — `shell=False`; command list format; no string injection risk
- Destructive commands (`rm -rf`, format, etc.) are subject to GUARDRAILS check → owner TOTP required
- Required system packages: `sudo apt install scrot tesseract-ocr xdg-utils xdotool wmctrl`

## ⚠️ `type` Action — window_id Required (DESK-TYPE-1)

**Before using the `type` action, identify the target window with `get_windows` and always send the `window_id` parameter.**  
Without `window_id`, text goes to whichever window currently has keyboard focus — if the user has switched to another window (browser address bar, chat field, etc.), the text is written to the wrong place.

```
# CORRECT — targeted writing
{"action": "type", "text": "user@example.com", "window_id": "0x05000003", "delay_ms": 12}

# WRONG — focus-dependent, unsafe
{"action": "type", "text": "user@example.com", "delay_ms": 12}
```

## Automation Rules & Preference Order

**vision_query and screenshot are the last resort.** Each screenshot fills the context window; when many accumulate, the Vision API returns a `many-image requests (2000px)` error.

**Hard limits:**
- Max **15 calls in a 5-minute sliding window** for `vision_query` (server-side enforced; `settings.desktop_vision_max_per_session`).
- Screenshots are automatically **resized to 1280px width** (`settings.desktop_screenshot_max_width`).

**Preference order (top to bottom):**
1. **Blind navigation** — Fill URL/form with `xdotool type`, `xdotool key`, navigate with `Tab`/`Enter`. Do not take screenshots.
2. **Terminal API** — Fetch HTML/JSON with `curl`, `wget`, `jq`; parse structured data.
3. **Playwright (FEAT-13)** — `/internal/browser/*` endpoints; click/type with DOM selector, without vision.
4. **Single verification screenshot** — ONE screenshot + OCR at a critical checkpoint (login successful? cart filled?).
5. **vision_query** — Only when coordinate detection is absolutely necessary (closing dynamic popups, etc.).

**Pre-task Vision check (DESK-LOGIN-3):** Before starting a desktop automation task, call the `check_vision` action. If it returns `available=false`, notify the user and switch to Playwright with DOM-based navigation — do not call vision_query.
```
POST /internal/desktop {"action": "check_vision"}
→ {"ok": true, "available": false, "fallback": "playwright", "message": "⚠️ ..."}
```

**If you see Captcha / SMS 2FA:** Stop, notify the user via `/internal/send_media` or notification, do not continue.

**If you exceed rate limit:** Fall back to DOM/xdotool path, wait for the window to reset (5 min), or temporarily increase the limit.

## Login Automation Strategy (DESK-LOGIN-1)

For web login tasks, **use Playwright `/internal/browser/*` endpoints — do not use Desktop API (xdotool/screenshot/vision_query).** Playwright finds form fields directly with DOM selectors; no coordinate guessing, screenshot loops, or Vision API needed.

**Standard login flow:**
```
1. POST /internal/browser {"action":"goto", "url":"https://site.com/login"}
2. POST /internal/browser {"action":"get_credential", "site_slug":"site_slug", "field":"user"}
   → {"ok":true, "value":"username"}
3. POST /internal/browser {"action":"get_credential", "site_slug":"site_slug", "field":"pass"}
   → {"ok":true, "value":"password"}
4. POST /internal/browser {"action":"fill", "selector":"input[name='username']", "value":"<user>"}
5. POST /internal/browser {"action":"fill", "selector":"input[name='password']", "value":"<pass>"}
6. POST /internal/browser {"action":"click", "selector":"button[type='submit']"}
7. POST /internal/browser {"action":"wait_for", "selector":".dashboard, .profile, [class*=welcome]", "timeout":10000}
8. POST /internal/browser {"action":"screenshot"}  ← SINGLE verification screenshot
9. POST /internal/send_media {"path":"/tmp/login_result.png", "caption":"Login result"}
```

**Fallback order if selector not found:**
1. Try alternative selector: `input[type='email']`, `#username`, `#login-form input:first-child`
2. Fetch HTML with `get_content` → find the correct selector
3. Run `document.querySelectorAll('input')` with `eval` → list form fields
4. **Last resort:** Fall back to Desktop API (xdotool) only if no inputs can be found in DOM

**Rules:**
- Always retrieve credentials with the `get_credential` action — do not hardcode, do not read `.env`
- Verify login success with `get_text` or `wait_for` — prefer DOM check over screenshot
- Do not rely on autofill popup — Playwright `fill()` already writes the value directly to the input
- Save session with `save_session` — cookies are loaded automatically on the next login
- If screen lock is detected (screenshot returns black), run `loginctl unlock-session` first, then continue with Playwright — Desktop API `unlock_screen` alone may not be sufficient
- **Use `cdp_click` with care** — bypasses Playwright's actionability checks (visible, stable, enabled). Enables clicking hidden or disabled buttons (e.g. "Delete Account"). Use only when standard `click` fails and you are confident the selector is correct; prefer in performance-critical scenarios, not general navigation

## Sending media (BUG-DESK-SEND-1)
When a `screenshot` or `record_screen` action completes successfully, call the **`/internal/send_media`** endpoint using the `path` or `paths` field from the response — otherwise the file is not forwarded to WhatsApp/Telegram.

```
POST http://localhost:8010/internal/send_media
Content-Type: application/json
{"path": "/tmp/wa_screenshot.png", "caption": "Screenshot"}
{"paths": ["/tmp/mon0.png", "/tmp/mon1.png"], "caption": "All monitors"}
```

- `path` — single file; `paths` — multi-monitor list (one must be specified)
- `caption` — optional description (default: empty)
- `to` — target; uses `settings.owner_id` if not specified (usually not needed)
- MIME type is auto-detected from extension: `image/*` → image, `video/*` → video, other → document
- Response: `{"ok": true, "results": [{"path": "...", "ok": true}]}`

**Usage flow (screenshot):**
```
1. POST /internal/desktop {"action": "screenshot"}
   → {"ok": true, "path": "/tmp/wa_screenshot.png"}
2. POST /internal/send_media {"path": "/tmp/wa_screenshot.png", "caption": "Screenshot"}
   → {"ok": true, "results": [...]}
```
