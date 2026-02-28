# Empulse

Activity monitoring dashboard for [Emby](https://emby.media) media servers. Track who's watching what, view playback history, graphs, and manage notifications.

![Empulse Dashboard](docs/screenshot.png)

## Quick Start

### 1. Get your Emby API key

In Emby, go to **Settings > API Keys** and create a new key for Empulse.

### 2. Run with Docker

```bash
docker run -d \
  -p 8189:8189 \
  -v empulse-data:/app/data \
  -e EMBY_URL=http://your-emby-server:8096 \
  -e EMBY_API_KEY=your_api_key_here \
  -e DB_PATH=/app/data/empulse.db \
  ghcr.io/empul-dev/empulse:latest
```

Or with Docker Compose (see `docker-compose.yml`):

```bash
docker compose up -d
```

Open [http://localhost:8189](http://localhost:8189) in your browser.

Log in with your Emby username and password.

## Configuration

All settings are via environment variables (in `.env` or `docker-compose.yml`):

| Variable | Default | Description |
|----------|---------|-------------|
| `EMBY_URL` | `http://localhost:8096` | Your Emby server URL |
| `EMBY_API_KEY` | *(required)* | Emby API key |
| `EMPULSE_PORT` | `8189` | Web UI port |
| `EMPULSE_HOST` | `0.0.0.0` | Bind address |
| `POLL_INTERVAL` | `10` | Seconds between Emby session polls |
| `AUTH_PASSWORD` | *(optional)* | Fallback admin password (works when Emby is unreachable) |
| `DISABLE_UPDATE_CHECK` | `false` | Set `true` to disable the automatic update checker |

## Features

- **Live Activity** -- Active streams in real-time with player, quality, and transcode details
- **Stop Streams** -- Remotely stop active playback sessions
- **History** -- Full playback history with search, filtering, and sorting
- **Graphs** -- Daily/monthly play counts, watch heatmap, completion rates, bandwidth stats
- **Users / Libraries** -- Per-user and per-library statistics
- **Re-watch Detection** -- Tracks when content is watched again
- **Notifications** -- Discord, Telegram, email, ntfy, and webhook alerts
- **Newsletter** -- Scheduled email digests of recent activity

## Updating

Empulse checks for new releases daily and shows a banner on the Settings page when an update is available.

To update with Docker Compose:

```bash
docker compose pull && docker compose up -d
```

## Architecture

- **Backend**: Python / FastAPI / Uvicorn
- **Frontend**: Jinja2 templates, htmx, Chart.js
- **Database**: SQLite (auto-created on first run)
- **Deployment**: Docker (Python 3.13 Alpine)

## Development

```bash
# Create virtual environment
python3 -m venv .venv && source .venv/bin/activate

# Install dependencies
pip install -e ".[dev]"

# Run locally (auto-reload)
uvicorn empulse.app:create_app --factory --reload --port 8189

# Run tests
pytest tests/

# Lint & format
ruff check empulse/
ruff format empulse/
```

## License

MIT
