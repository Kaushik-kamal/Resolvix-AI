"""Configuration settings for ops-api."""
from pathlib import Path
from typing import Annotated

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Ops API settings loaded from environment."""
    
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")
    
    # Server
    port: int = 8100
    
    # Database
    database_url: str = "sqlite:///./data/resolvix.db"
    
    # Security
    service_key: str = Field(..., description="X-Service-Key for runtime auth")
    session_secret: str = Field(..., min_length=32, description="Session cookie signing secret")
    seed_password: str = "DemoPassword123!"
    
    # URLs
    ops_public_url: str = "http://localhost:8100"
    cors_origins: str = "http://localhost:5173"
    
    # Runtime integration
    runtime_mode: str = "mock"  # mock | real
    runtime_url: str = "http://localhost:8000"
    
    # Notifications
    notify_mode: str = "mock"  # mock | twilio ("live" is accepted as an alias for twilio)
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from_number: str = Field("", validation_alias=AliasChoices("TWILIO_FROM", "TWILIO_FROM_NUMBER", "twilio_from_number"))
    notify_async: bool | None = None  # None: async for twilio, synchronous for mock
    sms_send_timeout_s: float = 5.0   # per provider attempt; one retry after a failure
    sms_poll_enabled: bool = True     # one delayed status poll when Twilio cannot call us back (localhost)
    sms_poll_delay_s: float = 10.0
    
    # Config files (relative to ops/api directory)
    departments_file: str = "../../contracts/config/departments.yaml"
    urgency_rules_file: str = "../../contracts/config/urgency_rules.yaml"
    sms_templates_file: str = "../../contracts/config/sms_templates.yaml"
    seed_users_file: str = "seed_users.yaml"
    
    session_cookie_secure: bool | None = None  # None: Secure when OPS_PUBLIC_URL is https

    # Staff only see their own department (admin and service see all)
    staff_scope_enabled: bool = True

    # Login brute-force guard (attempts per minute per client IP; 0 disables)
    login_rate_limit_per_min: int = 10

    # Knowledge base
    kb_import_max_bytes: int = 2 * 1024 * 1024
    kb_import_max_lines: int = 2000
    kb_publish_timeout_s: float = 30.0

    # Gaps: "keywords" (default). "embedding" is a feature flag that needs a cloud embedding key (see BLOCKERS.md)
    gap_cluster_strategy: str = "keywords"
    embedding_api_key: str = ""  # OpenAI-compatible embeddings API; empty => embedding strategy unavailable
    embedding_api_url: str = "https://api.openai.com/v1/embeddings"
    embedding_model: str = "text-embedding-3-small"

    # Timezone
    timezone: str = "Asia/Kolkata"
    
    # Seed
    seed_users_on_startup: bool = True
    
    def resolve_path(self, relative_path: str) -> Path:
        """Resolve a relative file path against the ops/api directory."""
        # __file__ is in resolvix_ops/config.py, so go up to ops/api
        base_dir = Path(__file__).parent.parent
        return (base_dir / relative_path).resolve()
    
    @property
    def cookie_secure(self) -> bool:
        """Session cookie Secure flag: on whenever the public URL is https."""
        if self.session_cookie_secure is not None:
            return self.session_cookie_secure
        return self.ops_public_url.lower().startswith("https://")

    @property
    def runtime_live(self) -> bool:
        """Publish talks to the real voice runtime (RUNTIME_MODE=real|live) instead of answering from a fixture."""
        return self.runtime_mode.strip().lower() in {"real", "live"}

    @property
    def sms_mode(self) -> str:
        """Normalised notify mode: "mock" or "twilio"."""
        mode = self.notify_mode.strip().lower()
        return "twilio" if mode in {"twilio", "live"} else mode

    @property
    def sms_async(self) -> bool:
        """Send status-change SMS from a worker thread instead of inside the PATCH request."""
        return self.notify_async if self.notify_async is not None else self.sms_mode == "twilio"

    @property
    def sms_result_mode(self) -> str:
        """SmsResult.mode value per contract: "mock" or "live"."""
        return "live" if self.sms_mode == "twilio" else "mock"

    @property
    def cors_origins_list(self) -> list[str]:
        """Parse CORS_ORIGINS as comma-separated list."""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


def load_settings() -> Settings:
    """Load and validate settings."""
    return Settings()  # type: ignore[call-arg]
