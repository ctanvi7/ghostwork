"""Sarvam voice prompts: assignee language, translation, storage-hosted audio, fallbacks."""

from urllib.parse import parse_qs, urlparse
from xml.etree import ElementTree

import pytest

from config import Config
from services.approver_service import voice_language
from services.sarvam_service import SarvamError
from services.supabase_service import get_service


@pytest.mark.parametrize("freshdesk,expected", [
    ("en", "en-IN"), ("hi", "hi-IN"), ("ta-IN", "ta-IN"), ("TE", "te-IN"), ("or", "od-IN"),
    ("fr", "en-IN"), (None, "en-IN"), ("", "en-IN"),
])
def test_freshdesk_language_maps_to_sarvam(freshdesk, expected):
    assert voice_language(freshdesk) == expected


class FakeBucket:
    def __init__(self):
        self.uploads, self.removed = {}, []

    def upload(self, path, data, options):
        assert options["content-type"] == "audio/wav"
        self.uploads[path] = data

    def download(self, path):
        return self.uploads[path]

    def remove(self, paths):
        self.removed.extend(paths)


@pytest.fixture
def voice_env(app, monkeypatch):
    import services.voice_approval_service as voice

    for name, value in {"VOBIZ_AUTH_ID": "id", "VOBIZ_AUTH_TOKEN": "tok", "VOBIZ_FROM_NUMBER": "+911111111111",
                        "PUBLIC_BASE_URL": "https://demo.example.org", "SARVAM_API_KEY": "key"}.items():
        monkeypatch.setattr(Config, name, value)
    service = get_service()
    execution_id = service.create_execution(1, ticket_id=3, refund_amount=32000)
    service.update_execution(execution_id, status="WAITING_FOR_APPROVAL")
    approval_id = service.create_approval(execution_id, amount=32000)

    calls = {"tts": [], "translate": [], "dial": {}}
    monkeypatch.setattr(voice, "synthesize", lambda text, language_code="en-IN":
                        calls["tts"].append((text, language_code)) or b"RIFF-" + language_code.encode())
    monkeypatch.setattr(voice, "translate", lambda text, target:
                        calls["translate"].append(target) or f"[{target}] {text}")
    monkeypatch.setattr(voice, "place_approval_call",
                        lambda answer, hangup, to: calls["dial"].update(answer=answer, hangup=hangup) or "call-1")
    return voice, execution_id, approval_id, calls


def _approver(monkeypatch, voice, language):
    monkeypatch.setattr(voice, "resolve_approver", lambda ticket_id: {
        "to": "+919876543210", "masked": "+91********10", "source": "ticket_assignee",
        "agent_id": 55, "note": None, "language": language})


def _answer(client, calls):
    params = {k: v[0] for k, v in parse_qs(urlparse(calls["dial"]["answer"]).query).items()}
    return ElementTree.fromstring(client.post("/api/webhooks/vobiz", query_string=params).data), params


def test_hindi_assignee_hears_translated_sarvam_audio_from_storage(client, voice_env, monkeypatch):
    voice, execution_id, approval_id, calls = voice_env
    bucket = FakeBucket()
    monkeypatch.setattr(voice, "_storage", lambda create=True: bucket)
    _approver(monkeypatch, voice, "hi-IN")

    response = client.post(f"/api/executions/{execution_id}/call-approver")
    assert response.status_code == 202
    assert response.get_json()["language"] == "hi-IN"

    # Every message translated to Hindi and spoken with the Hindi voice.
    assert set(calls["translate"]) == {"hi-IN"} and len(calls["translate"]) == len(voice.MESSAGES)
    assert all(lang == "hi-IN" and text.startswith("[hi-IN]") for text, lang in calls["tts"])
    assert len(bucket.uploads) == len(voice.MESSAGES)

    xml, params = _answer(client, calls)
    play = xml.find("./Gather/Play").text
    # Always this app's audio route: Vobiz silently skipped Supabase signed URLs.
    assert play.startswith(f"https://demo.example.org/api/voice/audio/{approval_id}/request?")
    parsed = urlparse(play)
    assert client.get(f"{parsed.path}?{parsed.query}").data == b"RIFF-hi-IN"
    # Exactly one voice: the Hindi Sarvam audio, never also a robotic English
    # fallback stacked after it (that pushes Gather's listening window later
    # and trains the caller to press a key before it's actually open).
    assert xml.find("./Gather/Speak") is None
    assert xml.find("./Speak") is None

    # Hangup deletes the stored prompts.
    params["action"] = "hangup"
    client.post("/api/webhooks/vobiz", query_string=params)
    assert sorted(bucket.removed) == sorted(bucket.uploads)


def test_english_is_default_and_skips_translation(client, voice_env, monkeypatch):
    voice, execution_id, _, calls = voice_env
    monkeypatch.setattr(voice, "_storage", lambda create=True: FakeBucket())
    _approver(monkeypatch, voice, "en-IN")

    client.post(f"/api/executions/{execution_id}/call-approver")
    assert calls["translate"] == []
    assert any("32,000 rupees" in text for text, _ in calls["tts"])


def test_rejection_and_approval_messages_are_sarvam_audio(client, voice_env, monkeypatch):
    voice, execution_id, _, calls = voice_env
    monkeypatch.setattr(voice, "_storage", lambda create=True: FakeBucket())
    monkeypatch.setattr(voice, "run_execution", lambda execution_id: None)
    _approver(monkeypatch, voice, "en-IN")
    client.post(f"/api/executions/{execution_id}/call-approver")

    _, params = _answer(client, calls)
    params["action"] = "choice"
    raw = client.post("/api/webhooks/vobiz", query_string=params, data={"Digits": "1"}).data
    done = ElementTree.fromstring(raw)
    assert "approved" in done.find("./Play").text
    assert done.find("./Hangup") is not None


def test_sarvam_request_prompt_is_a_single_voice(client, voice_env, monkeypatch):
    """Only the Sarvam Play, never also a Vobiz Speak stacked after it - a second
    message pushes Gather's listening window later than the caller expects."""
    voice, execution_id, _, calls = voice_env
    monkeypatch.setattr(voice, "_storage", lambda create=True: FakeBucket())
    _approver(monkeypatch, voice, "en-IN")
    client.post(f"/api/executions/{execution_id}/call-approver")

    answer, params = _answer(client, calls)
    assert answer.find("./Gather/Play") is not None
    assert answer.find("./Gather/Speak") is None

    # An invalid key repeats the prompt (still a single voice); nothing is decided.
    params["action"] = "choice"
    again = ElementTree.fromstring(
        client.post("/api/webhooks/vobiz", query_string=params, data={"Digits": "7"}).data
    )
    assert again.find("./Gather/Play") is not None
    assert again.find("./Gather/Speak") is None
    assert get_service().get_execution(execution_id)["status"] == "WAITING_FOR_APPROVAL"


def test_closing_message_uses_sarvam_audio_even_when_storage_is_down(client, voice_env, monkeypatch):
    """The decision message is served from the app route after the decision is
    recorded, so the approver hears it in the same Sarvam voice as the prompt."""
    voice, execution_id, approval_id, calls = voice_env

    def broken_storage(create=True):
        raise RuntimeError("storage down")

    monkeypatch.setattr(voice, "_storage", broken_storage)
    _approver(monkeypatch, voice, "en-IN")
    client.post(f"/api/executions/{execution_id}/call-approver")

    _, params = _answer(client, calls)
    params["action"] = "choice"
    done = ElementTree.fromstring(
        client.post("/api/webhooks/vobiz", query_string=params, data={"Digits": "2"}).data
    )
    play = done.find("./Play").text
    assert f"/api/voice/audio/{approval_id}/rejected?" in play
    assert done.find("./Speak") is None
    assert done.find("./Hangup") is not None
    parsed = urlparse(play)
    assert client.get(f"{parsed.path}?{parsed.query}").data == b"RIFF-en-IN"


def test_decision_audio_only_matches_the_recorded_decision(client, voice_env, monkeypatch):
    """After a rejection the "approved" message can't be fetched, and vice versa."""
    voice, execution_id, approval_id, calls = voice_env
    monkeypatch.setattr(voice, "_storage", lambda create=True: FakeBucket())
    _approver(monkeypatch, voice, "en-IN")
    client.post(f"/api/executions/{execution_id}/call-approver")

    _, params = _answer(client, calls)
    params["action"] = "choice"
    client.post("/api/webhooks/vobiz", query_string=params, data={"Digits": "2"})
    token = params["token"]
    assert client.get(f"/api/voice/audio/{approval_id}/rejected?token={token}").status_code == 200
    assert client.get(f"/api/voice/audio/{approval_id}/approved?token={token}").status_code == 404
    assert client.get(f"/api/voice/audio/{approval_id}/request?token={token}").status_code == 404


def test_other_server_instance_loads_prompt_from_storage_without_sarvam(client, voice_env, monkeypatch):
    """Serverless: Vobiz often reaches an instance that never prepared the call.
    It must load the stored copy (fast), not call Sarvam while Vobiz waits."""
    voice, execution_id, approval_id, calls = voice_env
    bucket = FakeBucket()
    monkeypatch.setattr(voice, "_storage", lambda create=True: bucket)
    _approver(monkeypatch, voice, "en-IN")
    client.post(f"/api/executions/{execution_id}/call-approver")

    xml, _ = _answer(client, calls)
    voice._audio_cache.clear()  # a fresh instance: nothing in memory
    tts_before = len(calls["tts"])
    parsed = urlparse(xml.find("./Gather/Play").text)
    assert client.get(f"{parsed.path}?{parsed.query}").data == b"RIFF-en-IN"
    assert len(calls["tts"]) == tts_before  # no Sarvam call at fetch time


def test_flaky_upload_is_retried(client, voice_env, monkeypatch):
    """A stale pooled connection fails once ("Server disconnected"); the retry succeeds."""
    voice, execution_id, approval_id, calls = voice_env

    class FlakyBucket(FakeBucket):
        failed = False

        def upload(self, path, data, options):
            if not FlakyBucket.failed:
                FlakyBucket.failed = True
                raise RuntimeError("Server disconnected")
            super().upload(path, data, options)

    bucket = FlakyBucket()
    monkeypatch.setattr(voice, "_storage", lambda create=True: bucket)
    _approver(monkeypatch, voice, "en-IN")
    client.post(f"/api/executions/{execution_id}/call-approver")

    files = get_service().select_one("approvals", {"id": approval_id})["raw_response_json"]["prompt_files"]
    assert set(files) == set(voice.MESSAGES)  # every prompt stored despite the failure


def test_closing_message_is_a_single_voice_when_storage_succeeded(client, voice_env, monkeypatch):
    """Only the Sarvam Play for the closing message, never also a Vobiz Speak
    stacked right after it - one clear voice, not two different ones back to back."""
    voice, execution_id, _, calls = voice_env
    bucket = FakeBucket()
    monkeypatch.setattr(voice, "_storage", lambda create=True: bucket)
    _approver(monkeypatch, voice, "en-IN")
    client.post(f"/api/executions/{execution_id}/call-approver")

    _, params = _answer(client, calls)
    params["action"] = "choice"
    done = ElementTree.fromstring(
        client.post("/api/webhooks/vobiz", query_string=params, data={"Digits": "1"}).data
    )
    assert done.find("./Play") is not None
    assert done.find("./Speak") is None
    assert done.find("./Hangup") is not None


def test_prompts_cleaned_up_after_decision(client, voice_env, monkeypatch):
    """The hangup that follows a decision deletes the stored prompts. Vobiz only
    runs <Hangup> after the closing <Play> finishes, so nothing is mid-fetch."""
    voice, execution_id, approval_id, calls = voice_env
    bucket = FakeBucket()
    monkeypatch.setattr(voice, "_storage", lambda create=True: bucket)
    _approver(monkeypatch, voice, "en-IN")
    client.post(f"/api/executions/{execution_id}/call-approver")

    _, params = _answer(client, calls)
    params["action"] = "choice"
    client.post("/api/webhooks/vobiz", query_string=params, data={"Digits": "2"})
    assert get_service().select_one("approvals", {"id": approval_id})["status"] == "REJECTED"

    params["action"] = "hangup"
    assert client.post("/api/webhooks/vobiz", query_string=params).status_code == 200
    assert sorted(bucket.removed) == sorted(bucket.uploads)
    params["token"] = "wrong"
    assert client.post("/api/webhooks/vobiz", query_string=params).status_code == 403


def test_prompts_deleted_immediately_when_call_ends_with_no_decision(client, voice_env, monkeypatch):
    """No decision means no closing message was queued, so it's always safe to
    delete right away - no race with an in-flight Play to worry about."""
    voice, execution_id, approval_id, calls = voice_env
    bucket = FakeBucket()
    monkeypatch.setattr(voice, "_storage", lambda create=True: bucket)
    _approver(monkeypatch, voice, "en-IN")
    client.post(f"/api/executions/{execution_id}/call-approver")

    _, params = _answer(client, calls)
    params["action"] = "hangup"
    assert client.post("/api/webhooks/vobiz", query_string=params).status_code == 200
    assert sorted(bucket.removed) == sorted(bucket.uploads)
    assert get_service().select_one("approvals", {"id": approval_id})["status"] == "PENDING"


def test_storage_failure_falls_back_to_app_audio_route(client, voice_env, monkeypatch):
    voice, execution_id, approval_id, calls = voice_env

    def broken_storage(create=True):
        raise RuntimeError("storage down")

    monkeypatch.setattr(voice, "_storage", broken_storage)
    _approver(monkeypatch, voice, "hi-IN")
    assert client.post(f"/api/executions/{execution_id}/call-approver").status_code == 202

    xml, _ = _answer(client, calls)
    play = xml.find("./Gather/Play").text
    assert play.startswith(f"https://demo.example.org/api/voice/audio/{approval_id}/request")
    parsed = urlparse(play)
    assert client.get(f"{parsed.path}?{parsed.query}").data == b"RIFF-hi-IN"


def test_translation_failure_speaks_english(client, voice_env, monkeypatch):
    voice, execution_id, _, calls = voice_env
    monkeypatch.setattr(voice, "_storage", lambda create=True: FakeBucket())

    def failing_translate(text, target):
        raise SarvamError("translate down")

    monkeypatch.setattr(voice, "translate", failing_translate)
    _approver(monkeypatch, voice, "ta-IN")
    client.post(f"/api/executions/{execution_id}/call-approver")
    assert all(lang == "en-IN" for _, lang in calls["tts"])


def test_sarvam_down_uses_vobiz_speak(client, voice_env, monkeypatch):
    voice, execution_id, _, calls = voice_env

    def failing_tts(text, language_code="en-IN"):
        raise SarvamError("tts down")

    monkeypatch.setattr(voice, "synthesize", failing_tts)
    _approver(monkeypatch, voice, "hi-IN")
    response = client.post(f"/api/executions/{execution_id}/call-approver")
    assert response.get_json()["language"] == "en-IN"

    xml, _ = _answer(client, calls)
    assert xml.find("./Gather/Speak").text.startswith("GhostWork refund approval request for 32,000 rupees")
