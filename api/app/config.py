"""Runtime configuration for the API service, read from environment variables.

Plain env-var reads rather than a settings library - there are only a few
settings and this needs no extra dependency.
"""

import os


class Settings:
    def __init__(self) -> None:
        self.harness_url: str = os.environ.get("HARNESS_URL", "http://localhost:8001")
        self.environment: str = os.environ.get("ENVIRONMENT", "dev")
        # Identity Platform's browser config, handed to the login screen by
        # GET /config. Public by design (every browser that loads the app
        # sees them) but kept out of the repo all the same.
        self.firebase_api_key: str = os.environ.get("FIREBASE_API_KEY", "")
        self.firebase_auth_domain: str = os.environ.get("FIREBASE_AUTH_DOMAIN", "")

    @property
    def is_dev(self) -> bool:
        return self.environment == "dev"


settings = Settings()
