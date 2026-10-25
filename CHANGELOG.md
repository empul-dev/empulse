# Changelog

## Unreleased

- Graphs: added "Concurrent Streams", showing the peak number of simultaneous streams per day and how many of them were transcodes.
- Security: removed the unused `/api/recent-history` endpoint. It showed every user's latest plays, including IP addresses, to viewer accounts.
- Security: images under `/api/img/` now require a login. The login page poster wall uses a new `/api/login-posters/` endpoint that only serves already cached posters, so anonymous visitors can no longer browse library artwork by item ID.
- The settings backup download now uses SQLite's backup API, so it includes recent changes that were still in the write-ahead log.
- Restoring a database in settings no longer overwrites the open database. The upload is checked, including a trial run of the startup migrations, and applied at the next restart with the same protected restore used by the command line. The previous database is kept in an `empulse.db.before-restore-*` directory.
- Restore uploads are streamed to disk, limited to 500 MB, and only one can run at a time.

## 0.2.21

- Users table can be sorted by user, total plays, total duration, or last seen by clicking the column headers.
- Updated FastAPI, Uvicorn, websockets, pydantic-settings, aiosqlite, python-dotenv and python-multipart to their current releases.
- Updated the GitHub Actions used for tests, security scans and Docker image builds.

## 0.2.20

- Removed the newsletter, its schedule, settings page and API endpoints, and the now unused `cryptography` dependency. Startup backs up existing databases before removing the newsletter configuration table, including the stored SMTP password.
- Kept playback history, statistics, live dashboard updates, and the generated secret key in update backups so restores to earlier releases still work.
- "Last N days" now means today plus the N-1 days before it, starting at midnight in the display timezone, instead of a rolling N×24 hours. Stat cards, charts and the period comparison now cover the same whole days.
- Dates, hours and weekdays in charts now use each play's own UTC offset, so plays are grouped correctly across daylight-saving changes. Plays per month are grouped by local month.
- Every daily chart now shows all days in the range, including days without plays. Previously the stacked, stream-type and bitrate charts skipped them.
- Added 7d/30d/90d/1y time-range buttons to the dashboard. The selected range and metric are kept when the stat cards refresh.
- Fixed the login page poster wall showing no posters when its cache was empty.

## 0.2.19

- Removed notification channels, automatic playback and new-media alerts, their settings and API endpoints. Startup backs up existing databases before removing the old channel configuration and delivery-log tables.
- Kept the newsletter, its schedule and encrypted SMTP password, playback history, and live dashboard updates.

## 0.2.18

- Added verified local database backups before release upgrades, including the generated secret key when used. Backups are retained in the persistent data volume.
- Added transactional startup migrations and an offline restore command with WAL handling and recovery copies. Failed backups stop the upgrade; failed migrations roll back.
- Kept notification support in this release so users receive backup protection before its removal in 0.2.19.

## 0.2.8

- Security (Wave 1 of the STRIDE action plan):
  - Restricted per-user history views, exports, and charts to admins and the owning user (previously any logged-in viewer could see any user's watch history).
  - Added real account-level login lockout with escalating durations (15m → 1h → 24h), independent of source IP.
  - Added per-user rate limiting on authenticated API requests.
  - Notification channel secrets (webhook URLs/headers, SMTP password, bot tokens) are now encrypted at rest, with automatic migration of existing plaintext secrets.
  - Notification failure logs are now scrubbed of tokens/secrets before being written.
- Added capture and display of Emby's `TranscodeReasons` — the Stream Info modal now shows a human-readable reason (e.g. "Video codec not supported") whenever a session transcodes, instead of requiring a log dive.

## 0.2.2

- Redesigned the newsletter email into a richer poster-based layout for movies and TV shows.
- Added inline newsletter images so posters render reliably in email clients.
- Grouped recently added TV episodes by show with season and episode summaries.
- Expanded newsletter metadata with runtime, genres, taglines, overviews, and star ratings.
- Kept the newsletter styling aligned with the Empulse dark theme.
