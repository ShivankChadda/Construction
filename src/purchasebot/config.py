"""Runtime settings, read from environment variables or a .env file."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- WhatsApp Cloud API (Meta) ---
    wa_phone_number_id: str = ""
    wa_access_token: str = ""
    wa_app_secret: str = ""  # used to verify X-Hub-Signature-256 on every webhook
    wa_verify_token: str = ""  # any random string; must match what you type in Meta's webhook setup
    wa_graph_version: str = "v23.0"
    # Utility template used when a person hasn't messaged the bot in 24h (Meta rule).
    wa_template_name: str = "action_required"
    wa_template_lang: str = "en"

    # --- Claude (message understanding) ---
    # The Anthropic SDK reads ANTHROPIC_API_KEY itself; this copy only decides
    # whether to use Claude or the offline rule-based parser.
    anthropic_api_key: str = ""
    claude_model: str = "claude-opus-5-5"
    claude_effort: str = "medium"

    # --- Sarvam AI (voice notes in Hindi / Indian languages) ---
    sarvam_api_key: str = ""
    sarvam_model: str = "saaras:v4"

    # --- Google Drive + Sheets (purchase register, PDFs, backups) ---
    google_auth_mode: str = "none"  # none | oauth | service_account
    google_oauth_client_id: str = ""
    google_oauth_client_secret: str = ""
    google_oauth_refresh_token: str = ""
    google_service_account_file: str = ""
    google_drive_root_folder_id: str = ""
    google_sheet_id: str = ""

    # --- App ---
    database_path: str = "data/purchasebot.db"
    roster_path: str = "config/roster.yaml"
    pdf_dir: str = "data/pdfs"
    backup_dir: str = "data/backups"
    signing_key: str = ""  # base64 Ed25519 seed; generated into data/signing.key when empty
    signing_key_path: str = "data/signing.key"
    public_base_url: str = "http://localhost:8000"
    timezone: str = "Asia/Kolkata"
    admin_token: str = ""

    # --- Controls ---
    price_alert_pct: float = 5.0  # flag a line when the rate is this much above the last purchase
    recent_purchase_days: int = 10  # flag repeat purchases of the same item for the same site
    approval_reminder_hours: float = 4.0
    max_approval_reminders: int = 3
    draft_reminder_minutes: int = 60
    daily_digest_hour: int = 20  # 24h clock, local time; -1 disables
    scheduler_interval_seconds: int = 300
    allow_unsigned_webhooks: bool = False  # only for local testing


@lru_cache
def get_settings() -> Settings:
    return Settings()
