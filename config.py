import os
from decimal import Decimal
from typing import Dict, List
from urllib.parse import urlparse

from dotenv import load_dotenv

load_dotenv()


class Config:
    """Application configuration loaded from environment."""

    # Flask
    SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "dev-key-change-in-production")
    DEBUG = os.getenv("FLASK_DEBUG", "false").lower() == "true"
    TESTING = os.getenv("FLASK_TESTING", "false").lower() == "true"

    # API
    MAX_CONTENT_LENGTH = 1_000_000  # 1 MB

    # Database
    DB_BACKEND = os.getenv("DB_BACKEND", "supabase")  # "supabase" or "memory"
    SUPABASE_URL = os.getenv("SUPABASE_URL")
    SUPABASE_KEY = os.getenv("SUPABASE_KEY")

    # External APIs
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
    CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-5")
    FRESHDESK_DOMAIN = os.getenv("FRESHDESK_DOMAIN")
    FRESHDESK_API_KEY = os.getenv("FRESHDESK_API_KEY")
    FRESHDESK_FALLBACK = os.getenv("FRESHDESK_FALLBACK")  # "cache" or None
    SARVAM_API_KEY = os.getenv("SARVAM_API_KEY")
    VOBIZ_API_KEY = os.getenv("VOBIZ_API_KEY")  # Legacy name for the auth token
    VOBIZ_AUTH_ID = os.getenv("VOBIZ_AUTH_ID")
    VOBIZ_AUTH_TOKEN = os.getenv("VOBIZ_AUTH_TOKEN") or VOBIZ_API_KEY
    VOBIZ_FROM_NUMBER = os.getenv("VOBIZ_FROM_NUMBER")
    APPROVER_PHONE = os.getenv("APPROVER_PHONE")

    # Governance
    AUTO_APPROVAL_LIMIT = Decimal("25000")  # ₹25,000
    REQUIRE_APPROVER_AUTH = os.getenv("REQUIRE_APPROVER_AUTH", "false").lower() == "true"

    # Public base URL for webhooks
    PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:5000")

    # Execution
    EXECUTOR_TIMEOUT_SECONDS = int(os.getenv("EXECUTOR_TIMEOUT_SECONDS", "120"))

    @classmethod
    def derive_tier(cls) -> str:
        """
        Derive the fallback tier (A, B, or C) based on configured integrations.

        Tier A: All integrations available (Freshdesk, Claude, Vobiz, Sarvam)
        Tier B: Core integrations (Freshdesk, Claude, web approval only)
        Tier C: Fallback (memory DB, cached ticket, deterministic path)
        """
        has_freshdesk = bool(cls.FRESHDESK_DOMAIN and cls.FRESHDESK_API_KEY)
        has_claude = bool(cls.ANTHROPIC_API_KEY)
        has_vobiz = cls.voice_call_configured()

        if has_freshdesk and has_claude and has_vobiz and bool(cls.SARVAM_API_KEY):
            return "A"
        elif has_freshdesk and has_claude:
            return "B"
        else:
            return "C"

    @classmethod
    def get_integrations_status(cls) -> Dict[str, bool]:
        """Return which integrations are configured (no credentials leaked)."""
        return {
            "supabase": bool(cls.SUPABASE_URL and cls.SUPABASE_KEY),
            "freshdesk": bool(cls.FRESHDESK_DOMAIN and cls.FRESHDESK_API_KEY),
            "claude": bool(cls.ANTHROPIC_API_KEY),
            "vobiz": cls.voice_call_configured(),
            "sarvam": bool(cls.SARVAM_API_KEY),
        }

    @classmethod
    def voice_call_configured(cls) -> bool:
        """A call needs credentials, numbers, and a provider-reachable callback."""
        callback_host = urlparse(cls.PUBLIC_BASE_URL).hostname
        return bool(
            cls.VOBIZ_AUTH_ID
            and cls.VOBIZ_AUTH_TOKEN
            and cls.VOBIZ_FROM_NUMBER
            and cls.APPROVER_PHONE
            and cls.PUBLIC_BASE_URL.startswith("https://")
            and callback_host not in ("localhost", "127.0.0.1", "::1")
            and "..." not in cls.VOBIZ_FROM_NUMBER
            and "..." not in cls.APPROVER_PHONE
        )

    @classmethod
    def validate_at_startup(cls) -> List[str]:
        """
        Validate critical config at startup. Return list of warnings.
        """
        warnings = []

        if cls.SECRET_KEY == "dev-key-change-in-production" and not cls.TESTING:
            warnings.append("WARNING: FLASK_SECRET_KEY is not set. Using development default.")

        if cls.DEBUG and not cls.TESTING:
            warnings.append("WARNING: FLASK_DEBUG is enabled. Disable in production.")

        tier = cls.derive_tier()
        if tier == "C":
            warnings.append("INFO: Running in Tier C (fallback mode). Supabase and/or Freshdesk not configured.")

        return warnings
