import os
from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Noaises home directory (~/.noaises)
    noaises_home: Path = Field(default = Path.home()/ ".noaises", validation_alias= "NOAISES_HOME")
    
    @property
    def noaises_home_resolved(self) -> Path:
        """Resolve noaises_home, expanding ~ to user home directory."""
        return self.noaises_home.expanduser()

# Global settings instance
settings = Settings()
