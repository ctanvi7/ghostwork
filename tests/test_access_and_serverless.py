"""Hosted deployment: app password gate and serverless-safe voice audio."""

import base64

import pytest

from config import Config


def _basic(user, password):
    return {"Authorization": "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()}


@pytest.fixture
def password_on(monkeypatch):
    monkeypatch.setattr(Config, "APP_USERNAME", "ghostwork")
    monkeypatch.setattr(Config, "APP_PASSWORD", "s3cret")


def test_pages_and_api_require_login(client, password_on):
    for path in ("/", "/api/executions", "/api/integrations"):
        response = client.get(path)
        assert response.status_code == 401, path
        assert "Basic" in response.headers["WWW-Authenticate"]
    assert client.post("/api/approvals/1/approve").status_code == 401


def test_correct_login_is_accepted_and_wrong_is_rejected(client, password_on):
    assert client.get("/api/executions", headers=_basic("ghostwork", "s3cret")).status_code == 200
    assert client.get("/api/executions", headers=_basic("ghostwork", "wrong")).status_code == 401
    assert client.get("/api/executions", headers=_basic("admin", "s3cret")).status_code == 401


def test_health_and_vobiz_callbacks_stay_reachable(client, password_on):
    assert client.get("/api/health").status_code == 200
    # Reaches the webhook's own token check (403), not the login gate (401).
    assert client.post("/api/webhooks/vobiz?approval_id=1&token=bad&action=answer").status_code == 403
    assert client.get("/api/voice/audio/1/request?token=bad").status_code == 404


def test_hosted_without_password_fails_closed(client, monkeypatch):
    monkeypatch.setattr(Config, "APP_PASSWORD", None)
    monkeypatch.setattr(Config, "IS_HOSTED", True)
    assert client.get("/api/executions").status_code == 503
    assert client.get("/api/health").status_code == 200


def test_local_without_password_stays_open(client, monkeypatch):
    monkeypatch.setattr(Config, "APP_PASSWORD", None)
    monkeypatch.setattr(Config, "IS_HOSTED", False)
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
    monkeypatch.setattr(voice, "synthesize", lambda text: prompts.append(text) or b"RIFF-wav")

    assert voice.get_audio(approval_id, token, "request") == b"RIFF-wav"
    assert "32,000 rupees" in prompts[0]
    xml = voice._xml_prompt(service.select_one("approvals", {"id": approval_id}), token)
    assert "<Play>" in xml
