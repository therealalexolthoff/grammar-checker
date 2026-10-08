"""Runtime configuration for the harness service."""

import os


class Settings:
    def __init__(self) -> None:
        self.mock_mode: bool = os.environ.get("HARNESS_MOCK_MODE", "true").lower() == "true"
        self.vertex_project_id: str = os.environ.get("VERTEX_PROJECT_ID", "")
        # "us" multi-region endpoint - see docs/ARCHITECTURE.md section 2.
        self.vertex_region: str = os.environ.get("VERTEX_REGION", "us")


settings = Settings()
