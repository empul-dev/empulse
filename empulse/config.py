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
    empulse_host: str = "127.0.0.1"
    empulse_port: int = 8189
    poll_interval: int = 10
    db_path: str = str(_PROJECT_DIR / "empulse.db")
    auth_password: str = ""
    secret_key: str = ""

    model_config = {"env_file_encoding": "utf-8"}


settings = Settings()

# Auto-generate a persistent secret key if not provided
if not settings.secret_key:
    import logging as _logging
    import secrets as _secrets
    _secret_file = Path(settings.db_path).parent / ".empulse_secret"
    try:
        if _secret_file.exists():
            settings.secret_key = _secret_file.read_text().strip()
        if not settings.secret_key:
            settings.secret_key = _secrets.token_hex(32)
            _secret_file.write_text(settings.secret_key + "\n")
            _secret_file.chmod(0o600)
    except OSError as _e:
        _logging.getLogger("empulse.config").warning(
            "Cannot persist secret key to %s: %s. "
            "Sessions will not survive restarts.",
            _secret_file, _e,
        )
        settings.secret_key = _secrets.token_hex(32)
