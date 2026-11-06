from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BIOAGENT_", env_file=".env", extra="ignore")

    llm_provider: Literal["deepseek", "ollama"] = "deepseek"
    deepseek_api_key: SecretStr | None = None
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-v4-flash"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen3:8b"
    api_base_url: str = "http://localhost:8000"
    runs_dir: Path = Path("runs")
    data_dir: Path = Path("data")
    checkpoint_db: Path = Path("checkpoints.sqlite")
    workbench_db: Path = Path("data/workbench.sqlite")
    local_allowed_hosts: tuple[str, ...] = ("127.0.0.1", "localhost", "::1")
    local_dev_origin: str | None = None
    rscript: str = "Rscript"

    @field_validator("local_dev_origin")
    @classmethod
    def local_vite_origin(cls, value: str | None) -> str | None:
        if value is None:
            return None
        url = urlsplit(value)
        if (
            url.scheme != "http"
            or url.hostname not in {"localhost", "127.0.0.1", "::1"}
            or url.port != 5173
            or url.path
            or url.query
            or url.fragment
            or url.username is not None
            or value != f"http://{url.netloc}"
        ):
            raise ValueError("local_dev_origin must be an exact local Vite origin on port 5173")
        return value
