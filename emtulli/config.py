from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    emby_url: str = "http://localhost:8096"
    emby_api_key: str = ""
    emtulli_host: str = "0.0.0.0"
    emtulli_port: int = 8189
    poll_interval: int = 10
    db_path: str = "emtulli.db"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
