"""Voice callbacks must preserve the deterministic human approval boundary."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from urllib.parse import parse_qs, urlparse
from xml.etree import ElementTree

import pytest

from config import Config
from services.supabase_service import get_service


@pytest.fixture
def pending_execution(app, monkeypatch):
    monkeypatch.setattr(Config, "VOBIZ_AUTH_ID", "test-id")
    monkeypatch.setattr(Config, "VOBIZ_AUTH_TOKEN", "test-token")
    monkeypatch.setattr(Config, "VOBIZ_FROM_NUMBER", "+911111111111")
    monkeypatch.setattr(Config, "APPROVER_PHONE", "+912222222222")
    monkeypatch.setattr(Config, "PUBLIC_BASE_URL", "https://demo.example.org")
    monkeypatch.setattr(Config, "SARVAM_API_KEY", None)
    service = get_service()
    execution_id = service.create_execution(1, ticket_id=2048, refund_amount=32000)
    service.update_execution(execution_id, status="WAITING_FOR_APPROVAL")
    approval_id = service.create_approval(execution_id, amount=32000)
    return execution_id, approval_id


def _start_voice(client, monkeypatch, execution_id):
    import services.voice_approval_service as voice

    urls = {}

    def fake_call(answer_url, hangup_url):
        urls["answer"] = answer_url
        urls["hangup"] = hangup_url
        return "call-test-1"

    monkeypatch.setattr(voice, "place_approval_call", fake_call)
    response = client.post(f"/api/executions/{execution_id}/call-approver")
    assert response.status_code == 202
    parsed = urlparse(urls["answer"])
    params = {key: values[0] for key, values in parse_qs(parsed.query).items()}
    return params


def test_voice_approval_needs_second_dtmf_confirmation(client, pending_execution, monkeypatch):
    import services.voice_approval_service as voice

    execution_id, approval_id = pending_execution
    monkeypatch.setattr(voice, "run_execution", lambda execution_id: None)
    params = _start_voice(client, monkeypatch, execution_id)
    assert get_service().select_one("approvals", {"id": approval_id}).get("decided_at") is None

    answer = client.post("/api/webhooks/vobiz", query_string=params)
    assert answer.status_code == 200
    assert b"<Gather" in answer.data
    assert b"inputType=\"dtmf\"" in answer.data

    params["action"] = "choice"
    first = client.post("/api/webhooks/vobiz", query_string=params, data={"Digits": "1"})
    assert first.status_code == 200
    assert b"Final confirmation" in first.data
    assert get_service().get_execution(execution_id)["status"] == "WAITING_FOR_APPROVAL"

    params["action"] = "confirm"
    second = client.post("/api/webhooks/vobiz", query_string=params, data={"Digits": "1"})
    assert second.status_code == 200
    assert get_service().get_execution(execution_id)["status"] == "APPROVED"
    assert get_service().select_one("approvals", {"id": approval_id})["status"] == "APPROVED"


def test_voice_reject_stops_execution(client, pending_execution, monkeypatch):
    execution_id, approval_id = pending_execution
    params = _start_voice(client, monkeypatch, execution_id)
    params["action"] = "choice"
    response = client.post("/api/webhooks/vobiz", query_string=params, data={"Digits": "2"})
    assert response.status_code == 200
    assert get_service().get_execution(execution_id)["status"] == "REJECTED"
    assert get_service().select_one("approvals", {"id": approval_id})["status"] == "REJECTED"


def test_sarvam_prompt_is_played_only_for_valid_callback(client, pending_execution, monkeypatch):
    import services.voice_approval_service as voice

    execution_id, _ = pending_execution
    monkeypatch.setattr(Config, "SARVAM_API_KEY", "test-key")
    monkeypatch.setattr(voice, "synthesize", lambda prompt: b"RIFF-audio")
    params = _start_voice(client, monkeypatch, execution_id)
    answer = client.post("/api/webhooks/vobiz", query_string=params)
    xml = ElementTree.fromstring(answer.data)
    audio_url = xml.find("./Gather/Play").text
    parsed = urlparse(audio_url)
    assert client.get(f"{parsed.path}?{parsed.query}").data == b"RIFF-audio"
    assert client.get(f"{parsed.path}?token=wrong").status_code == 404


def test_invalid_or_replayed_callback_cannot_approve(client, pending_execution, monkeypatch):
    execution_id, _ = pending_execution
    params = _start_voice(client, monkeypatch, execution_id)
    params["action"] = "confirm"
    params["token"] = "wrong"
    assert client.post("/api/webhooks/vobiz", query_string=params, data={"Digits": "1"}).status_code == 403
    assert get_service().get_execution(execution_id)["status"] == "WAITING_FOR_APPROVAL"


def test_speech_approval_only_requests_confirmation(client, pending_execution, monkeypatch):
    import services.voice_approval_service as voice

    execution_id, _ = pending_execution
    params = _start_voice(client, monkeypatch, execution_id)
    monkeypatch.setattr(voice, "fetch_recording", lambda url: b"audio")
    monkeypatch.setattr(voice, "transcribe", lambda audio, filename="response.wav": "I approve this refund")
    params["action"] = "record"
    response = client.post("/api/webhooks/vobiz", query_string=params, data={"RecordingUrl": "https://api.vobiz.ai/recording.wav"})
    assert response.status_code == 200
    assert b"Final confirmation" in response.data
    assert get_service().get_execution(execution_id)["status"] == "WAITING_FOR_APPROVAL"


def test_ambiguous_or_negated_speech_never_approves(client, pending_execution, monkeypatch):
    import services.voice_approval_service as voice

    execution_id, _ = pending_execution
    params = _start_voice(client, monkeypatch, execution_id)
    monkeypatch.setattr(voice, "fetch_recording", lambda url: b"audio")
    params["action"] = "record"
    for transcript in ("maybe approve", "approve or reject"):
        monkeypatch.setattr(voice, "transcribe", lambda audio, filename="response.wav", text=transcript: text)
        client.post("/api/webhooks/vobiz", query_string=params, data={"RecordingUrl": "https://api.vobiz.ai/recording.wav"})
        assert get_service().get_execution(execution_id)["status"] == "WAITING_FOR_APPROVAL"
    monkeypatch.setattr(voice, "transcribe", lambda audio, filename="response.wav": "do not approve")
    client.post("/api/webhooks/vobiz", query_string=params, data={"RecordingUrl": "https://api.vobiz.ai/recording.wav"})
    assert get_service().get_execution(execution_id)["status"] == "REJECTED"


def test_call_failure_preserves_web_approval(client, pending_execution, monkeypatch):
    import services.voice_approval_service as voice
    from services.vobiz_service import VobizError

    execution_id, approval_id = pending_execution
    monkeypatch.setattr(voice, "place_approval_call", lambda *args: (_ for _ in ()).throw(VobizError("offline")))
    response = client.post(f"/api/executions/{execution_id}/call-approver")
    assert response.status_code == 502
    assert get_service().get_execution(execution_id)["status"] == "WAITING_FOR_APPROVAL"
    assert get_service().select_one("approvals", {"id": approval_id})["status"] == "PENDING"


def test_voice_unconfigured_returns_web_fallback(client, pending_execution, monkeypatch):
    execution_id, _ = pending_execution
    monkeypatch.setattr(Config, "PUBLIC_BASE_URL", "http://localhost:5000")
    response = client.post(f"/api/executions/{execution_id}/call-approver")
    assert response.status_code == 409
    assert "web approval" in response.get_json()["error"]["message"]


def test_concurrent_opposite_decisions_only_one_wins(pending_execution):
    from app import InvalidStateError
    from services.approvals_service import decide

    execution_id, approval_id = pending_execution
    barrier = Barrier(2)

    def choose(decision):
        barrier.wait()
        try:
            decide(execution_id, decision, channel="test", approver="test_manager")
            return "won"
        except (ValueError, InvalidStateError):
            return "lost"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(choose, ("approve", "reject")))

    assert sorted(results) == ["lost", "won"]
    execution_status = get_service().get_execution(execution_id)["status"]
    approval_status = get_service().select_one("approvals", {"id": approval_id})["status"]
    assert execution_status == approval_status
