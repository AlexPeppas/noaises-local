from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Noaises home directory (~/.noaises)
    noaises_home: Path = Field(
        default=Path.home() / ".noaises", validation_alias="NOAISES_HOME"
    )

    # Streaming mode (token-by-token output + streaming TTS)
    enable_streaming: bool = Field(default=True)

    # Memory distillation
    memory_distill_enabled: bool = Field(default=True)
    memory_distill_interval: int = Field(default=5)  # every N turns
    memory_distill_model: str = Field(default="claude-haiku-4-5-20251001")

    @property
    def noaises_home_resolved(self) -> Path:
        """Resolve noaises_home, expanding ~ to user home directory."""
        return self.noaises_home.expanduser()


# Global settings instance
settings = Settings()
