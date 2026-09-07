# Changelog

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
