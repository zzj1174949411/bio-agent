from pathlib import Path
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="BIOAGENT_", env_file=".env", extra="ignore"
    )

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
    rscript: str = "Rscript"
