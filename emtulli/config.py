import os
from pathlib import Path
from dotenv import load_dotenv
from pydantic_settings import BaseSettings

# Find .env by walking up from this file
_THIS_DIR = Path(__file__).resolve().parent
for _candidate in [_THIS_DIR.parent, _THIS_DIR, Path.cwd()]:
    _env_file = _candidate / ".env"
    if _env_file.exists():
        load_dotenv(_env_file)
        break

_PROJECT_DIR = _THIS_DIR.parent


class Settings(BaseSettings):
    emby_url: str = "http://localhost:8096"
    emby_api_key: str = ""
    emtulli_host: str = "0.0.0.0"
    emtulli_port: int = 8189
    poll_interval: int = 10
    db_path: str = str(_PROJECT_DIR / "emtulli.db")

    model_config = {"env_file_encoding": "utf-8"}


settings = Settings()
