# Empulse

Activity monitoring dashboard for [Emby](https://emby.media) media servers. Track who's watching what, view playback history, graphs, and manage notifications.

## Quick Start

### 1. Get your Emby API key

In Emby, go to **Settings > API Keys** and create a new key for Empulse.

### 2. Configure

```bash
cp .env.example .env
```

Edit `.env` with your Emby server details:

```
EMBY_URL=http://your-emby-server:8096
EMBY_API_KEY=your_api_key_here
```

### 3. Run with Docker

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
| `EMTULLI_PORT` | `8189` | Web UI port |
| `EMTULLI_HOST` | `0.0.0.0` | Bind address |
| `POLL_INTERVAL` | `10` | Seconds between Emby session polls |
| `AUTH_PASSWORD` | *(optional)* | Fallback admin password (works when Emby is unreachable) |

## Features

- **Live Activity** -- See active streams in real-time with player, quality, and transcode details
- **History** -- Full playback history with search, filtering, and sorting
- **Graphs** -- Play count, duration, and daily activity charts
- **Users / Libraries** -- Per-user and per-library statistics
- **Notifications** -- Discord, Telegram, Slack, email, ntfy, and webhook alerts
- **Newsletter** -- Scheduled email digests of recent activity

## Architecture

- **Backend**: Python / Starlette / Uvicorn
- **Frontend**: Jinja2 templates, htmx, Chart.js
- **Database**: SQLite (auto-created on first run)
- **Deployment**: Docker (Python 3.13)

## Development

```bash
# Create virtual environment
python3 -m venv .venv && source .venv/bin/activate

# Install dependencies
pip install -e .

# Run locally
uvicorn empulse.app:create_app --factory --reload --port 8189
```

## License

MIT
