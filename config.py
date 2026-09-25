import os
from decimal import Decimal
from pathlib import Path
from typing import Dict, List
from urllib.parse import urlparse

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")


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
    FRESHDESK_PROVIDER = os.getenv("FRESHDESK_PROVIDER", "mcp")  # "mcp" or "rest"
    # When provider=mcp, an MCP failure must not be silently masked by REST
    # unless this is explicitly enabled.
    FRESHDESK_ALLOW_REST_FALLBACK = os.getenv("FRESHDESK_ALLOW_REST_FALLBACK", "false").lower() == "true"
    FRESHDESK_FALLBACK = os.getenv("FRESHDESK_FALLBACK")  # "cache" or None
    # Real Freshdesk ticket used by the refund demo. Freshdesk assigns ticket IDs
    # itself, so this must match a ticket that actually exists in your account.
    FRESHDESK_DEMO_TICKET_ID = int(os.getenv("FRESHDESK_DEMO_TICKET_ID") or "2048")
    # API name of the Freshdesk custom field holding the refund amount. Freshdesk
    # prefixes "cf_" to the name you type, so check Admin > Ticket Fields.
    FRESHDESK_REFUND_AMOUNT_FIELD = os.getenv("FRESHDESK_REFUND_AMOUNT_FIELD") or "cf_refund_amount"
    # Close the Freshdesk ticket after a fully verified automation (closure_agent).
    FRESHDESK_AUTO_CLOSE = os.getenv("FRESHDESK_AUTO_CLOSE", "true").lower() == "true"
    # MCP Freshdesk (independent of REST API)
    MCP_FRESHDESK_URL = os.getenv("MCP_FRESHDESK_URL")  # e.g., https://domain.freshdesk.com/mcp
    MCP_FRESHDESK_AUTH_TOKEN = os.getenv("MCP_FRESHDESK_AUTH_TOKEN")  # Auth token for MCP server
    SARVAM_API_KEY = os.getenv("SARVAM_API_KEY")
    VOBIZ_API_KEY = os.getenv("VOBIZ_API_KEY")  # Legacy name for the auth token
    VOBIZ_AUTH_ID = os.getenv("VOBIZ_AUTH_ID")
    VOBIZ_AUTH_TOKEN = os.getenv("VOBIZ_AUTH_TOKEN") or VOBIZ_API_KEY
    VOBIZ_FROM_NUMBER = os.getenv("VOBIZ_FROM_NUMBER")
    # The number to call is the Freshdesk ticket assignee's; this is only a fallback.
    APPROVER_PHONE = os.getenv("APPROVER_PHONE")
    # Prepended to 10-digit local numbers from Freshdesk profiles (91 = India).
    VOBIZ_DEFAULT_COUNTRY_CODE = os.getenv("VOBIZ_DEFAULT_COUNTRY_CODE", "91")

    # Governance
    AUTO_APPROVAL_LIMIT = Decimal("25000")  # ₹25,000
    REQUIRE_APPROVER_AUTH = os.getenv("REQUIRE_APPROVER_AUTH", "false").lower() == "true"

    # Browser login for the whole app (see app.setup_access_protection).
    APP_USERNAME = os.getenv("APP_USERNAME") or "ghostwork"
    APP_PASSWORD = os.getenv("APP_PASSWORD")
    IS_HOSTED = bool(os.getenv("VERCEL"))

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
        if cls.FRESHDESK_PROVIDER == "mcp":
            has_freshdesk = bool(cls.MCP_FRESHDESK_URL and cls.MCP_FRESHDESK_AUTH_TOKEN)
        elif cls.FRESHDESK_PROVIDER == "rest":
            has_freshdesk = bool(cls.FRESHDESK_DOMAIN and cls.FRESHDESK_API_KEY)
        else:
            has_freshdesk = False
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
        """Return which integrations are configured (no credentials leaked).

        Freshdesk "configured" reflects ONLY the provider actually selected via
        FRESHDESK_PROVIDER. It does NOT silently fall back to reporting the
        other provider's status - if provider=mcp but MCP env vars are unset,
        this correctly reports configured=false rather than masking it by
        relabeling to "rest".
        """
        provider = cls.FRESHDESK_PROVIDER
        mcp_configured = bool(cls.MCP_FRESHDESK_URL and cls.MCP_FRESHDESK_AUTH_TOKEN)
        rest_configured = bool(cls.FRESHDESK_DOMAIN and cls.FRESHDESK_API_KEY)

        if provider == "mcp":
            freshdesk_configured = mcp_configured
        elif provider == "rest":
            freshdesk_configured = rest_configured
        else:
            freshdesk_configured = False

        freshdesk_status = {
            "configured": freshdesk_configured,
            "provider": provider,
        }

        # Safe diagnostic: which env VAR NAMES are missing (never values).
        if not freshdesk_configured:
            missing = []
            if provider == "mcp":
                if not cls.MCP_FRESHDESK_URL:
                    missing.append("MCP_FRESHDESK_URL")
                if not cls.MCP_FRESHDESK_AUTH_TOKEN:
                    missing.append("MCP_FRESHDESK_AUTH_TOKEN")
            elif provider == "rest":
                if not cls.FRESHDESK_DOMAIN:
                    missing.append("FRESHDESK_DOMAIN")
                if not cls.FRESHDESK_API_KEY:
                    missing.append("FRESHDESK_API_KEY")
            if missing:
                freshdesk_status["missing_config"] = missing

        return {
            "supabase": bool(cls.SUPABASE_URL and cls.SUPABASE_KEY),
            "freshdesk": freshdesk_status,
            "claude": bool(cls.ANTHROPIC_API_KEY),
            "vobiz": cls.voice_call_configured(),
            "sarvam": bool(cls.SARVAM_API_KEY),
        }

    @classmethod
    def freshdesk_ticket_url(cls, ticket_id) -> str | None:
        """Agent-portal link to a ticket, built from the configured host only (no credentials)."""
        try:
            ticket_id = int(ticket_id)
        except (TypeError, ValueError):
            return None
        host = None
        if cls.FRESHDESK_PROVIDER == "mcp" and cls.MCP_FRESHDESK_URL:
            host = urlparse(cls.MCP_FRESHDESK_URL).hostname
        else:
            host = cls.freshdesk_rest_host()
        if not host or not host.endswith(".freshdesk.com"):
            return None
        return f"https://{host}/a/tickets/{ticket_id}"

    @classmethod
    def freshdesk_rest_host(cls) -> str | None:
        """Accept FRESHDESK_DOMAIN as "acme", "acme.freshdesk.com" or "https://acme.freshdesk.com/"."""
        if not cls.FRESHDESK_DOMAIN:
            return None
        domain = cls.FRESHDESK_DOMAIN.strip().rstrip("/")
        if "://" in domain:
            domain = urlparse(domain).hostname or ""
        if not domain:
            return None
        return domain if domain.endswith(".freshdesk.com") else f"{domain}.freshdesk.com"

    @classmethod
    def voice_call_configured(cls) -> bool:
        """A call needs credentials, a caller ID, and a provider-reachable callback.

        The number to dial is resolved per call from the Freshdesk ticket assignee
        (services/approver_service.py), so APPROVER_PHONE is not required here.
        """
        callback_host = urlparse(cls.PUBLIC_BASE_URL).hostname
        return bool(
            cls.VOBIZ_AUTH_ID
            and cls.VOBIZ_AUTH_TOKEN
            and cls.VOBIZ_FROM_NUMBER
            and cls.PUBLIC_BASE_URL.startswith("https://")
            and callback_host not in ("localhost", "127.0.0.1", "::1")
            and "..." not in cls.VOBIZ_FROM_NUMBER
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
