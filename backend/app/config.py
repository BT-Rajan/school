"""Deployment configuration, read from SCES_* environment variables.

District-level settings that admins change at runtime live in the
districts table instead (see app.models.district).
"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SCES_", env_file=".env", extra="ignore")

    environment: str = "development"
    database_url: str = "mysql+pymysql://sces_app:sces_app@localhost:3306/sces?charset=utf8mb4"

    # HMAC key for login codes, recovery codes, invitation tokens and CSRF tokens.
    secret_key: str = Field(min_length=32)
    # 32-byte key, base64url encoded, for encrypting TOTP secrets at rest (FR-A13).
    encryption_key: str

    public_base_url: str = "http://localhost:5173"
    cookie_secure: bool = True
    # Trust X-Forwarded-For from the reverse proxy in front of the API.
    trust_proxy_headers: bool = True

    # Mail provider: console (development), smtp, or gmail (FR-N9).
    mail_provider: str = "console"
    mail_sender: str = "noreply@example.org"
    mail_sender_name: str = "School Cluster Evaluation System"
    smtp_host: str = "localhost"
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_starttls: bool = True
    gmail_client_id: str = ""
    gmail_client_secret: str = ""
    gmail_refresh_token: str = ""

    # Encrypted file objects (FR-FS1), on a volume outside the web root.
    storage_path: str = "/var/lib/sces/files"

    # Virus scanning (FR-FS3). "clamd" is required in production; "none" is for development only.
    virus_scanner: str = "clamd"
    clamd_host: str = "clamav"
    clamd_port: int = 3310

    # Check new passwords against the Have I Been Pwned range API (k-anonymity).
    # Fails open when the service cannot be reached; the bundled list still applies.
    breached_password_api: bool = False

    # Largest request bodies accepted (section 15): uploads, and everything else.
    # The upload limit must stay above the district's upload_max_mb setting.
    max_upload_request_mb: int = 60
    max_json_request_kb: int = 2048

    # General API rate limits per minute (section 15).
    rate_limit_user_per_minute: int = 300
    rate_limit_ip_per_minute: int = 1000


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    if settings.environment == "production" and settings.virus_scanner != "clamd":
        raise ValueError("SCES_VIRUS_SCANNER must be clamd in production")
    return settings
