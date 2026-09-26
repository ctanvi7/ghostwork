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


def test_sarvam_tts_validates_response(monkeypatch):
    monkeypatch.setattr(Config, "SARVAM_API_KEY", "test-key")
    calls = []

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return FakeResponse({"audios": [base64.b64encode(b"RIFF-audio").decode()]})

    monkeypatch.setattr(sarvam_service.requests, "post", fake_post)
    assert sarvam_service.synthesize("Approve refund") == b"RIFF-audio"
    assert calls[0][0].endswith("text-to-speech")
    assert calls[0][1]["headers"]["api-subscription-key"] == "test-key"
    assert calls[0][1]["json"]["speech_sample_rate"] == 8000  # telephony audio
    assert all("timeout" in kwargs for _, kwargs in calls)


def test_sarvam_malformed_response_fails_closed(monkeypatch):
    monkeypatch.setattr(Config, "SARVAM_API_KEY", "test-key")
    monkeypatch.setattr(sarvam_service.requests, "post", lambda *args, **kwargs: FakeResponse({"audios": []}))
    with pytest.raises(sarvam_service.SarvamError):
        sarvam_service.synthesize("Approve")


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
