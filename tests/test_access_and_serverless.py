"""Hosted deployment: sign-in pages, invite-code registration, serverless-safe voice audio."""

import pytest

from config import Config
from services import auth_service

INVITE = "invite-123"


@pytest.fixture
def auth_on(monkeypatch):
    monkeypatch.setattr(Config, "AUTH_REQUIRED", True)
    monkeypatch.setattr(Config, "REGISTRATION_CODE", INVITE)
    auth_service.clear_memory_users()
    yield
    auth_service.clear_memory_users()


def _register(client, email="aditi@example.com", password="correct-horse", code=INVITE, confirm=None):
    return client.post("/register", data={
        "name": "Aditi Rao", "email": email, "password": password,
        "confirm_password": confirm if confirm is not None else password, "invite_code": code,
    })


def test_pages_redirect_to_login_and_api_returns_401(client, auth_on):
    page = client.get("/executions")
    assert page.status_code == 302
    assert page.headers["Location"].startswith("/login?next=/executions")

    api = client.get("/api/executions")
    assert api.status_code == 401
    assert api.get_json()["error"]["code"] == "UNAUTHORIZED"
    assert client.post("/api/approvals/1/approve").status_code == 401


def test_login_page_uses_app_theme_and_public_routes_stay_open(client, auth_on):
    login = client.get("/login")
    assert login.status_code == 200
    assert b"GhostWork" in login.data and b"css/auth.css" in login.data
    assert client.get("/static/css/auth.css").status_code == 200
    assert client.get("/api/health").status_code == 200
    # Vobiz routes reach their own token checks, not the sign-in gate.
    assert client.post("/api/webhooks/vobiz?approval_id=1&token=bad&action=answer").status_code == 403
    assert client.get("/api/voice/audio/1/request?token=bad").status_code == 404


def test_register_requires_valid_invite_code(client, auth_on):
    response = _register(client, code="wrong")
    assert response.status_code == 400
    assert b"Invalid invite code" in response.data
    assert client.get("/api/executions").status_code == 401


@pytest.mark.parametrize("kwargs,message", [
    ({"password": "short"}, b"at least 8 characters"),
    ({"confirm": "different-pass"}, b"Passwords do not match"),
    ({"email": "not-an-email"}, b"valid email"),
])
def test_register_validates_input(client, auth_on, kwargs, message):
    response = _register(client, **kwargs)
    assert response.status_code == 400
    assert message in response.data


def test_register_closed_without_invite_code(client, auth_on, monkeypatch):
    monkeypatch.setattr(Config, "REGISTRATION_CODE", None)
    assert b"Registration is closed" in client.get("/register").data
    assert _register(client, code="").status_code == 400


def test_register_signs_in_and_duplicate_email_is_rejected(client, auth_on):
    response = _register(client)
    assert response.status_code == 302
    assert client.get("/api/executions").status_code == 200
    page = client.get("/")
    assert b"Aditi Rao" in page.data and b"Sign out" in page.data

    client.post("/logout")
    assert _register(client).status_code == 400


def test_login_logout_and_safe_redirect(client, auth_on):
    _register(client)
    client.post("/logout")
    assert client.get("/api/executions").status_code == 401

    wrong = client.post("/login", data={"email": "aditi@example.com", "password": "nope"})
    assert wrong.status_code == 401
    assert b"Incorrect email or password" in wrong.data

    ok = client.post("/login", data={"email": "ADITI@example.com", "password": "correct-horse",
                                     "next": "/executions"})
    assert ok.status_code == 302 and ok.headers["Location"] == "/executions"
    assert client.get("/api/executions").status_code == 200

    client.post("/logout")
    evil = client.post("/login", data={"email": "aditi@example.com", "password": "correct-horse",
                                       "next": "//evil.example.com"})
    assert evil.headers["Location"] == "/"


def test_passwords_are_hashed_not_stored(client, auth_on):
    _register(client)
    stored = auth_service._memory_users["aditi@example.com"]
    assert "correct-horse" not in str(stored)
    assert stored["password_hash"].startswith(("scrypt:", "pbkdf2:"))


def test_approval_records_signed_in_user(client, auth_on, monkeypatch):
    import routes.approvals as approvals_route
    from services.supabase_service import get_service

    monkeypatch.setattr(approvals_route, "run_execution", lambda execution_id: None)
    service = get_service()
    execution_id = service.create_execution(1, ticket_id=None, refund_amount=32000)
    service.update_execution(execution_id, status="WAITING_FOR_APPROVAL")
    approval_id = service.create_approval(execution_id, amount=32000)

    _register(client)
    assert client.post(f"/api/approvals/{approval_id}/approve").status_code == 200
    assert service.select_one("approvals", {"id": approval_id})["approver"] == "aditi@example.com"


def test_local_without_auth_stays_open(client, monkeypatch):
    monkeypatch.setattr(Config, "AUTH_REQUIRED", False)
    assert client.get("/api/executions").status_code == 200


def test_audio_regenerated_on_another_instance(app, monkeypatch):
    """Vobiz may fetch audio from a different serverless instance than the one that dialed."""
    import hashlib

    import services.voice_approval_service as voice
    from services.supabase_service import get_service

    service = get_service()
    execution_id = service.create_execution(1, ticket_id=None, refund_amount=32000)
    service.update_execution(execution_id, status="WAITING_FOR_APPROVAL")
    approval_id = service.create_approval(execution_id, amount=32000)
    token = "tok"
    service.transition_approval(approval_id, "PENDING", "PENDING", raw_response_json={
        "voice_token_hash": hashlib.sha256(token.encode()).hexdigest(), "sarvam_audio": True})

    voice._audio_cache.clear()  # fresh instance: nothing in memory
    prompts = []
    monkeypatch.setattr(voice, "synthesize", lambda text, language_code="en-IN": prompts.append(text) or b"RIFF-wav")

    assert voice.get_audio(approval_id, token, "request") == b"RIFF-wav"
    assert "32,000 rupees" in prompts[0]
    xml = voice._xml_prompt(service.select_one("approvals", {"id": approval_id}), token)
    assert "<Play>" in xml
