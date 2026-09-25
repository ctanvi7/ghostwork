"""Provider response validation and safe fallback behavior."""

import base64

import pytest
import requests

from config import Config
from services import sarvam_service, vobiz_service


class FakeResponse:
    def __init__(self, data, content=b"", status_code=200):
        self.data = data
        self.content = content
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError("provider failed")

    def json(self):
        return self.data


def test_sarvam_tts_and_stt_validate_responses(monkeypatch):
    monkeypatch.setattr(Config, "SARVAM_API_KEY", "test-key")
    calls = []

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        if url.endswith("text-to-speech"):
            return FakeResponse({"audios": [base64.b64encode(b"RIFF-audio").decode()]})
        return FakeResponse({"transcript": "I approve", "language_code": "en-IN"})

    monkeypatch.setattr(sarvam_service.requests, "post", fake_post)
    assert sarvam_service.synthesize("Approve refund") == b"RIFF-audio"
    assert sarvam_service.transcribe(b"audio") == "I approve"
    assert calls[0][1]["headers"]["api-subscription-key"] == "test-key"
    assert calls[1][1]["data"]["mode"] == "translate"
    assert all("timeout" in kwargs for _, kwargs in calls)


def test_sarvam_malformed_response_fails_closed(monkeypatch):
    monkeypatch.setattr(Config, "SARVAM_API_KEY", "test-key")
    monkeypatch.setattr(sarvam_service.requests, "post", lambda *args, **kwargs: FakeResponse({"audios": []}))
    with pytest.raises(sarvam_service.SarvamError):
        sarvam_service.synthesize("Approve")
    monkeypatch.setattr(sarvam_service.requests, "post", lambda *args, **kwargs: FakeResponse({"transcript": ""}))
    with pytest.raises(sarvam_service.SarvamError):
        sarvam_service.transcribe(b"audio")


def test_vobiz_call_uses_authenticated_api_and_validates_id(monkeypatch):
    monkeypatch.setattr(Config, "VOBIZ_AUTH_ID", "test-id")
    monkeypatch.setattr(Config, "VOBIZ_AUTH_TOKEN", "test-token")
    monkeypatch.setattr(Config, "VOBIZ_FROM_NUMBER", "+911111111111")
    monkeypatch.setattr(Config, "PUBLIC_BASE_URL", "https://demo.example.org")
    calls = []

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return FakeResponse({"request_uuid": "call-123"})

    monkeypatch.setattr(vobiz_service.requests, "post", fake_post)
    assert vobiz_service.place_approval_call(
        "https://demo.example.org/answer", "https://demo.example.org/hangup", "+912222222222") == "call-123"
    assert calls[0][1]["headers"]["X-Auth-ID"] == "test-id"
    assert calls[0][1]["json"]["to"] == "+912222222222"
    assert "timeout" in calls[0][1]

    monkeypatch.setattr(vobiz_service.requests, "post", lambda *args, **kwargs: FakeResponse({}))
    with pytest.raises(vobiz_service.VobizError):
        vobiz_service.place_approval_call(
            "https://demo.example.org/answer", "https://demo.example.org/hangup", "+912222222222")


def test_recording_download_rejects_untrusted_hosts_and_redirects(monkeypatch):
    with pytest.raises(vobiz_service.VobizError):
        vobiz_service.fetch_recording("http://127.0.0.1/private")
    with pytest.raises(vobiz_service.VobizError):
        vobiz_service.fetch_recording("https://api.vobiz.ai.evil.example/recording")
    monkeypatch.setattr(vobiz_service.requests, "get", lambda *args, **kwargs: FakeResponse({}, status_code=302))
    with pytest.raises(vobiz_service.VobizError):
        vobiz_service.fetch_recording("https://api.vobiz.ai/recording")


def test_access_log_redacts_voice_callback_token():
    import logging
    from app import VoiceTokenFilter

    record = logging.LogRecord(
        "werkzeug", logging.INFO, __file__, 1,
        'POST %s', ('/api/webhooks/vobiz?approval_id=1&token=private-token&action=choice',), None,
    )
    VoiceTokenFilter().filter(record)
    assert "private-token" not in record.getMessage()
    assert "token=[redacted]" in record.getMessage()
