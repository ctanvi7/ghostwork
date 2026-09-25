import hmac
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from flask import Flask, Response, jsonify, request

from config import Config


class AppError(Exception):
    """Base application error."""

    def __init__(
        self,
        message: str,
        code: str = "INTERNAL_ERROR",
        status_code: int = 500,
        details: Optional[Dict[str, Any]] = None,
    ):
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details or {}
        super().__init__(message)


class ValidationError(AppError):
    """Input validation error."""

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(message, code="VALIDATION_ERROR", status_code=422, details=details)


class NotFoundError(AppError):
    """Resource not found error."""

    def __init__(self, message: str):
        super().__init__(message, code="NOT_FOUND", status_code=404)


class InvalidStateError(AppError):
    """Invalid state transition error."""

    def __init__(self, message: str):
        super().__init__(message, code="INVALID_STATE", status_code=409)


class UpstreamError(AppError):
    """External API failure."""

    def __init__(self, message: str, provider: str | None = None):
        details = {"provider": provider} if provider else {}
        super().__init__(
            message, code="UPSTREAM_ERROR", status_code=502, details=details
        )


class RequestIdFilter(logging.Filter):
    """Logging filter that adds request_id to log records."""

    def filter(self, record):
        if not hasattr(record, "request_id"):
            record.request_id = "N/A"
        return True


class VoiceTokenFilter(logging.Filter):
    """Keep one-time callback tokens out of local HTTP access logs."""

    def filter(self, record):
        redact = lambda value: re.sub(r"([?&]token=)[^&\s]+", r"\1[redacted]", value)
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(redact(arg) if isinstance(arg, str) else arg for arg in record.args)
        return True


def setup_logging(app: Flask) -> None:
    """Configure structured logging with request IDs."""
    handler = logging.StreamHandler()
    handler.setLevel(logging.INFO)
    handler.addFilter(RequestIdFilter())
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - [%(request_id)s] - %(message)s"
    )
    handler.setFormatter(formatter)
    app.logger.addHandler(handler)
    app.logger.setLevel(logging.INFO)
    access_logger = logging.getLogger("werkzeug")
    if not any(isinstance(existing, VoiceTokenFilter) for existing in access_logger.filters):
        access_logger.addFilter(VoiceTokenFilter())


def setup_request_id_middleware(app: Flask) -> None:
    """Inject request ID into every request."""

    @app.before_request
    def before_request():
        request_id = request.headers.get("X-Request-ID")
        if not request_id:
            request_id = str(uuid.uuid4())
        request.request_id = request_id

    @app.after_request
    def after_request(response):
        response.headers["X-Request-ID"] = getattr(request, "request_id", "N/A")
        return response


# Reachable without the app password. Vobiz cannot log in, so its callbacks are
# instead protected by a per-call secret token checked in voice_approval_service.
PUBLIC_PATHS = ("/api/health",)
PUBLIC_PREFIXES = ("/api/webhooks/vobiz", "/api/voice/audio/")


def setup_access_protection(app: Flask) -> None:
    """Require a browser login (HTTP Basic) when APP_PASSWORD is set.

    On a hosted deployment (Vercel sets VERCEL=1) a missing password fails
    closed instead of leaving approvals open to anyone with the URL.
    """

    @app.before_request
    def require_login():
        path = request.path
        if path in PUBLIC_PATHS or path.startswith(PUBLIC_PREFIXES):
            return None
        if not Config.APP_PASSWORD:
            if Config.IS_HOSTED:
                return jsonify({"error": {"code": "ACCESS_NOT_CONFIGURED",
                                          "message": "Set APP_PASSWORD before using the hosted app"}}), 503
            return None  # local development

        auth = request.authorization
        valid = (
            auth is not None
            and hmac.compare_digest((auth.username or "").encode(), Config.APP_USERNAME.encode())
            and hmac.compare_digest((auth.password or "").encode(), Config.APP_PASSWORD.encode())
        )
        if valid:
            return None
        return Response("Login required", 401, {"WWW-Authenticate": 'Basic realm="GhostWork"'})


def setup_security_headers(app: Flask) -> None:
    """Add security headers to all responses."""

    @app.after_request
    def add_security_headers(response):
        response.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self' 'unsafe-inline'"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        return response


def setup_error_handlers(app: Flask) -> None:
    """Register centralized error handlers."""

    def error_response(error: AppError, request_id: str):
        return (
            {
                "error": {
                    "code": error.code,
                    "message": error.message,
                    "request_id": request_id,
                    "details": error.details,
                }
            },
            error.status_code,
        )

    @app.errorhandler(AppError)
    def handle_app_error(error: AppError):
        request_id = getattr(request, "request_id", "N/A")
        app.logger.error(f"{error.code}: {error.message}", extra={"details": error.details})
        return error_response(error, request_id)

    @app.errorhandler(404)
    def handle_not_found(e):
        request_id = getattr(request, "request_id", "N/A")
        error = NotFoundError("Endpoint not found")
        return error_response(error, request_id)

    @app.errorhandler(405)
    def handle_method_not_allowed(e):
        request_id = getattr(request, "request_id", "N/A")
        error = AppError(
            "Method not allowed", code="METHOD_NOT_ALLOWED", status_code=405
        )
        return error_response(error, request_id)

    @app.errorhandler(413)
    def handle_payload_too_large(e):
        request_id = getattr(request, "request_id", "N/A")
        error = AppError("Payload too large", code="PAYLOAD_TOO_LARGE", status_code=413)
        return error_response(error, request_id)

    @app.errorhandler(500)
    def handle_internal_error(e):
        request_id = getattr(request, "request_id", "N/A")
        app.logger.exception("Unhandled exception")
        error = AppError("Internal server error")
        return error_response(error, request_id)


def create_app(config_override: Optional[Dict[str, Any]] = None) -> Flask:
    """Create and configure the Flask application."""
    app = Flask(__name__)

    # Load config
    app.config.from_object(Config)
    if config_override:
        app.config.update(config_override)

    # Set max content length
    app.config["MAX_CONTENT_LENGTH"] = Config.MAX_CONTENT_LENGTH

    # Setup middleware and handlers
    setup_logging(app)
    setup_request_id_middleware(app)
    setup_access_protection(app)
    setup_security_headers(app)
    setup_error_handlers(app)

    # Validate config at startup (unless testing)
    if not app.config.get("TESTING"):
        warnings = Config.validate_at_startup()
        for warning in warnings:
            app.logger.warning(warning)

    # Register blueprints
    register_health_routes(app)
    register_blueprints(app)

    return app


def register_blueprints(app: Flask) -> None:
    """Register all blueprints for API routes."""
    from routes.approvals import approvals_bp
    from routes.discovery import discovery_bp
    from routes.executions import executions_bp
    from routes.ghostskills import ghostskills_bp
    from routes.pages import pages_bp
    from routes.workflows import workflows_bp
    from routes.voice import voice_bp

    app.register_blueprint(executions_bp)
    app.register_blueprint(workflows_bp)
    app.register_blueprint(approvals_bp)
    app.register_blueprint(ghostskills_bp)
    app.register_blueprint(discovery_bp)
    app.register_blueprint(pages_bp)
    app.register_blueprint(voice_bp)


def register_health_routes(app: Flask) -> None:
    """Register health and integrations endpoints."""

    @app.route("/api/health", methods=["GET"])
    def health():
        """Liveness check."""
        return (
            jsonify(
                {
                    "status": "ok",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            ),
            200,
        )

    @app.route("/api/integrations", methods=["GET"])
    def integrations():
        """Readiness check: which integrations are configured."""
        return (
            jsonify(
                {
                    "status": Config.derive_tier(),
                    "configured": Config.get_integrations_status(),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            ),
            200,
        )


if __name__ == "__main__":
    app = create_app()
    app.run(debug=Config.DEBUG)
