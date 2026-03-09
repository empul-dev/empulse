# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## Language & Stack

This project uses Python as the primary language, with HTML, CSS, and vanilla JS for the frontend. Always prefer Python conventions (type hints, PEP 8) for backend code.

## What is Empulse

Activity monitoring dashboard for Emby media servers. Tracks active streams, playback history, per-user/library stats, graphs, and notifications. Python async backend with server-rendered HTML frontend.

## Commands

```bash
# Install (dev)
pip install -e ".[dev]"

# Run dev server (auto-reload)
uvicorn empulse.app:create_app --factory --reload --port 8189

# Run all tests
pytest tests/

# Run a single test file
pytest tests/test_auth.py -v

# Run a specific test
pytest tests/test_auth.py::test_create_session_token -v

# Lint
ruff check empulse/

# Format
ruff format empulse/
```

Tests use pytest-asyncio with `asyncio_mode = "auto"` — all async test functions run automatically without `@pytest.mark.asyncio`. Test fixtures provide an in-memory SQLite database (`db`) and sample Emby session data.

## Architecture

### Backend (Python / FastAPI)

**Entry point:** `empulse/app.py` — `create_app()` factory. Lifespan initializes DB, clears sessions, launches background tasks (poller, Emby WebSocket, newsletter scheduler, poster cache), registers routers, applies auth + security header middleware.

**Routers:** `/` → `web/router.py` (HTML pages), `/api` → `web/api.py` (REST + htmx partials), `/ws` → `web/websocket.py` (browser push).

**Core pipeline:**
1. `activity/poller.py` — `SessionPoller` polls Emby API every N seconds
2. `activity/processor.py` — `ActivityProcessor` detects state transitions (start/pause/resume/stop/watched)
3. `activity/session_state.py` — `SessionStateTracker` holds in-memory active session state with pause event tracking
4. On stop → writes to `history` table with final stats

**Emby integration:** `emby/client.py` (async httpx client), `emby/models.py` (Pydantic models for Emby responses), `emby/websocket.py` (listens for Emby server events to trigger immediate polls).

**Database:** `database.py` — SQLite with aiosqlite, WAL mode. Single global connection via `get_db()`. Schema defined as `SCHEMA` constant. Migrations run in `_migrate()` on startup. Query modules in `db/` (history, users, libraries, stats).

**Auth:** `web/auth.py` — `AuthMiddleware` with HMAC-signed session tokens, rate limiting (5/5min per IP), CSRF origin checks, role-based access (admin/viewer).

**Notifications:** `notifications/engine.py` dispatches events through configured channels in `notifications/channels/` (Discord, webhook, email, Telegram, ntfy). Channels loaded from DB with 60s TTL cache.

**Config:** `config.py` — pydantic-settings loading from env vars / `.env`. Key vars: `EMBY_URL`, `EMBY_API_KEY`, `AUTH_PASSWORD`, `SECRET_KEY`, `POLL_INTERVAL`, `DB_PATH`.

### Frontend (Jinja2 / htmx / vanilla JS)

No build step. Server-rendered HTML with lightweight client-side enhancements.

- **Templates:** `templates/` — Jinja2 with `base.html` layout. `EmpulseTemplates` subclass auto-injects `current_user` and `csp_nonce`. `templates/partials/` for htmx-swappable fragments.
- **CSS:** PicoCSS (CDN) + `static/css/style.css` for custom styles.
- **JS:** `static/js/app.js` (~384 lines) — auto-reconnecting WebSocket, htmx event handlers, Chart.js rendering. No framework, no bundler.
- **Static files** served at `/static` via Starlette `StaticFiles`. Cache-busting via `{{ cache_v }}` global (unix timestamp at startup).

### Frontend ↔ Backend Communication

Three patterns:

1. **htmx partials** (primary) — `hx-get="/api/now-playing"` returns rendered HTML fragments. Triggers: page load, polling intervals, WebSocket-dispatched events.
2. **fetch → JSON** — Chart data (`/api/charts/*`), notification config, admin actions. JS calls `fetch()`, renders with Chart.js or updates DOM.
3. **WebSocket push** — Browser connects to `/ws`. Backend broadcasts `{"type": "refresh", "target": "now-playing"}` on activity changes. JS dispatches `refresh-{target}` event on `document.body`, which triggers htmx re-polls.

### Key Files

| File | Purpose |
|---|---|
| `empulse/app.py` | App factory, lifespan, middleware |
| `empulse/config.py` | Settings singleton (env vars) |
| `empulse/database.py` | Schema, migrations, `get_db()` |
| `empulse/web/router.py` | Page routes (HTML) |
| `empulse/web/api.py` | REST API + htmx partials |
| `empulse/web/auth.py` | Auth middleware, tokens, CSRF |
| `empulse/web/websocket.py` | Browser WebSocket manager |
| `empulse/activity/processor.py` | State transition detection |
| `empulse/notifications/engine.py` | Notification dispatcher |
| `empulse/static/js/app.js` | All client-side JS |
| `empulse/templates/base.html` | Base layout template |
| `pyproject.toml` | Dependencies, pytest config |

## Workflow

### Workflow Preferences
When making changes, run relevant tests and linters before considering a task complete. Use `bash` to verify changes work end-to-end rather than just editing files.

### Planning
- Enter plan mode for ANY non-trivial task (3+ steps or architectural decisions)
- If something goes sideways, STOP and re-plan immediately — don't keep pushing
- Use plan mode for verification steps, not just building
- Write detailed specs upfront to reduce ambiguity

### When to Use Subagents

**Direct handling (no subagent):**
- Single-file bug fixes (auth, template, CSS)
- Isolated features (new notification channel, new stats query, new db helper)
- Small refactors within one module
- Changes touching ≤2 files

**Subagent for research, then implement directly:**
- Understanding how a feature works before changing it (activity pipeline, pause tracking)
- Investigating coupling before a refactor
- Exploring Emby API behavior or DB migration edge cases

**Parallel subagents for cross-cutting changes:**
- New page/route: one subagent for API + DB queries, another for template + JS
- New metadata field end-to-end: schema/migrations, processor/models, routes/templates
- Notification system changes: engine logic vs channel implementations vs tests
- Any change touching 3+ modules with parallelizable work

**Always use subagents for:**
- Database schema changes (subagent designs schema + migration, main implements)
- Activity pipeline refactors (poller → processor → session_state are tightly coupled)
- Heavy refactors across `activity/`, `db/`, and `web/` layers

**Decision rule:** If the task touches 3+ files and parts can be done in parallel, use subagents. If it requires investigation before implementation, use a research subagent first. Otherwise, handle directly.

### Self-Improvement
- After ANY correction from the user: update `tasks/lessons.md` with the pattern
- Write rules for yourself that prevent the same mistake
- Ruthlessly iterate on these lessons until mistake rate drops
- Review lessons at session start for relevant project

### Verification
- Never mark a task complete without proving it works
- Diff behavior between main and your changes when relevant
- Ask yourself: "Would a staff engineer approve this?"
- Run tests, check logs, demonstrate correctness

### Elegance (Balanced)
- For non-trivial changes: pause and ask "is there a more elegant way?"
- If a fix feels hacky: "Knowing everything I know now, implement the elegant solution"
- Skip this for simple, obvious fixes — don't over-engineer

### Autonomous Bug Fixing
- When given a bug report: just fix it. Don't ask for hand-holding
- Point at logs, errors, failing tests — then resolve them
- Zero context switching required from the user

## Task Management

For complex tasks, break work into subtasks using TodoWrite to track progress. Update task status as you go so the user can see incremental progress.

1. **Plan First**: Write plan to `tasks/todo.md` with checkable items
2. **Verify Plan**: Check in before starting implementation
3. **Track Progress**: Mark items complete as you go
4. **Explain Changes**: High-level summary at each step
5. **Document Results**: Add review section to `tasks/todo.md`
6. **Capture Lessons**: Update `tasks/lessons.md` after corrections

## Git Identity

All commits and pushes MUST use the repo-local git config:
- **Name:** `empul-dev`
- **Email:** `empul-dev@users.noreply.github.com`

NEVER run `git config user.name` or `git config user.email` to change these. If a commit somehow shows a different author, stop and alert the user.

## Core Principles

- **Simplicity First**: Make every change as simple as possible. Impact minimal code.
- **No Laziness**: Find root causes. No temporary fixes. Senior developer standards.
- **Minimal Impact**: Changes should only touch what's necessary. Avoid introducing bugs.

## Key conventions

- Async throughout — all DB ops, HTTP calls, and route handlers use `async`/`await`
- Parameterized SQL queries only (no string interpolation)
- Database migrations go in `_migrate()` in `database.py` using `ALTER TABLE` with try/except for idempotency
- Pydantic models for all Emby API responses (`emby/models.py`) and settings (`config.py` using pydantic-settings)
- Settings loaded from env vars / `.env` file via `empulse/config.py` `settings` singleton
- Security headers (CSP, HSTS, X-Frame-Options) applied via middleware in `app.py`
- Auth tokens: HMAC-signed 5-part format `{timestamp}.{nonce}.{user_id_b64}.{role}.{hmac}`
