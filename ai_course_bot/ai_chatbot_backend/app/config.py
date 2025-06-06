from enum import Enum
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings


class EnvironmentEnum(str, Enum):
    """Allowed application environments."""
    dev = "dev"
    production = "production"
    test = "test"


class LLMModeEnum(str, Enum):
    """Allowed LLM modes for inference."""
    local = "local"
    remote = "remote"
    mock = "mock"


class Settings(BaseSettings):
    """Centralized backend configuration."""
    environment: EnvironmentEnum = Field(
        EnvironmentEnum.dev,
        description="The application environment: dev, production, or test"
    )
    llm_mode: Optional[LLMModeEnum] = Field(
        None,
        description="LLM mode: local, remote, or mock. Defaults based on environment if not set."
    )
    # TODO: Revise here, current deployed server seems to have a router path naming bug
    remote_model_url: str = "https://tai.berkeley.edu/api/chat"

    @property
    def effective_llm_mode(self) -> LLMModeEnum:
        """
        Determines the effective LLM mode.

        If `llm_mode` is explicitly set, that is used.
        Otherwise:
          - In test environment: defaults to 'mock'
          - In production environment: defaults to 'local'
          - Otherwise: defaults to 'mock'
        """
        if self.llm_mode is not None:
            return self.llm_mode
        if self.environment == EnvironmentEnum.test:
            return LLMModeEnum.mock
        elif self.environment == EnvironmentEnum.production:
            return LLMModeEnum.local
        else:
            return LLMModeEnum.mock

    class Config:
        env_file = ".env"


settings = Settings()
