from pathlib import Path
from pydantic_settings import BaseSettings

_PROJECT_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    emby_url: str = "http://localhost:8096"
    emby_api_key: str = ""
    emtulli_host: str = "0.0.0.0"
    emtulli_port: int = 8189
    poll_interval: int = 10
    db_path: str = str(_PROJECT_DIR / "emtulli.db")

    model_config = {
        "env_file": str(_PROJECT_DIR / ".env"),
        "env_file_encoding": "utf-8",
    }


settings = Settings()
