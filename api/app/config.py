"""Runtime configuration for the API service, read from environment variables.

Plain env-var reads rather than a settings library - there are only two
settings so far and this needs no extra dependency.
"""

import os


class Settings:
    def __init__(self) -> None:
        self.harness_url: str = os.environ.get("HARNESS_URL", "http://localhost:8001")
        self.environment: str = os.environ.get("ENVIRONMENT", "dev")

    @property
    def is_dev(self) -> bool:
        return self.environment == "dev"


settings = Settings()
