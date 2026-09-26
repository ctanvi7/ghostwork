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

    def fake_call(answer_url, hangup_url, to_number):
        urls["to"] = to_number
        urls["answer"] = answer_url
        urls["hangup"] = hangup_url
        return "call-test-1"

    monkeypatch.setattr(voice, "place_approval_call", fake_call)
    response = client.post(f"/api/executions/{execution_id}/call-approver")
    assert response.status_code == 202
    parsed = urlparse(urls["answer"])
    params = {key: values[0] for key, values in parse_qs(parsed.query).items()}
    return params


def test_single_keypress_1_approves_and_resumes(client, pending_execution, monkeypatch):
    import services.voice_approval_service as voice

    execution_id, approval_id = pending_execution
    resumed = []
    monkeypatch.setattr(voice, "run_execution", lambda execution_id: resumed.append(execution_id))
    params = _start_voice(client, monkeypatch, execution_id)
    assert get_service().select_one("approvals", {"id": approval_id}).get("decided_at") is None

    answer = client.post("/api/webhooks/vobiz", query_string=params)
    assert answer.status_code == 200
    xml = ElementTree.fromstring(answer.data)
    gather = xml.find("./Gather")
    assert gather.get("inputType") == "dtmf" and gather.get("numDigits") == "1"
    assert "press 1 to approve, or 2 to reject." in gather.find("./Speak").text
    assert xml.find("./Record") is None  # no spoken answers
    # No key press: Vobiz moves to the next element without calling the Gather
    # action, so control is handed back to our choice handler for a retry.
    redirect = xml.find("./Redirect")
    assert redirect is not None and "action=choice" in redirect.text
    assert xml.find("./Hangup") is None

    params["action"] = "choice"
    done = client.post("/api/webhooks/vobiz", query_string=params, data={"Digits": "1"})
    assert done.status_code == 200
    assert b"<Hangup" in done.data
    assert get_service().get_execution(execution_id)["status"] == "APPROVED"
    approval = get_service().select_one("approvals", {"id": approval_id})
    assert approval["status"] == "APPROVED" and approval["channel"] == "voice"
    assert approval["raw_response_json"]["method"] == "dtmf"
    assert resumed == [execution_id]


def test_other_keys_ask_again_and_never_decide(client, pending_execution, monkeypatch):
    execution_id, _ = pending_execution
    params = _start_voice(client, monkeypatch, execution_id)
    params["action"] = "choice"
    for digits in ("3", "9", "#", ""):
        again = client.post("/api/webhooks/vobiz", query_string=params, data={"Digits": digits})
        assert again.status_code == 200
        assert ElementTree.fromstring(again.data).find("./Gather") is not None
    assert get_service().get_execution(execution_id)["status"] == "WAITING_FOR_APPROVAL"


def test_gather_listening_window_is_within_vobiz_range(client, pending_execution, monkeypatch):
    """Listening starts at the tone; a missed press is retried, so the window stays short."""
    from services.voice_approval_service import GATHER_TIMEOUT_SECONDS

    execution_id, _ = pending_execution
    params = _start_voice(client, monkeypatch, execution_id)
    answer = ElementTree.fromstring(client.post("/api/webhooks/vobiz", query_string=params).data)
    gather = answer.find("./Gather")
    assert 5 <= int(gather.get("executionTimeout")) <= 60  # documented Vobiz range
    assert gather.get("executionTimeout") == GATHER_TIMEOUT_SECONDS


def test_silence_redirect_gets_a_retry_prompt_not_a_hangup(client, pending_execution, monkeypatch):
    """The Redirect after Gather arrives with no Digits; the first one must retry."""
    execution_id, approval_id = pending_execution
    params = _start_voice(client, monkeypatch, execution_id)
    answer = ElementTree.fromstring(client.post("/api/webhooks/vobiz", query_string=params).data)
    redirect_params = {k: v[0] for k, v in parse_qs(urlparse(answer.find("./Redirect").text).query).items()}

    retry = ElementTree.fromstring(client.post("/api/webhooks/vobiz", query_string=redirect_params).data)
    assert retry.find("./Gather") is not None
    assert "We didn't get a response" in retry.find("./Gather/Speak").text
    assert get_service().select_one("approvals", {"id": approval_id})["raw_response_json"]["voice_no_input_attempts"] == 1


def test_prompt_audio_ends_with_the_press_now_tone():
    import io
    import wave

    from services.voice_approval_service import _with_tone

    source = io.BytesIO()
    with wave.open(source, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\x00\x00" * 8000)  # 1 s of silence
    toned = _with_tone(source.getvalue())
    with wave.open(io.BytesIO(toned), "rb") as w:
        assert w.getframerate() == 8000 and w.getsampwidth() == 2
        assert w.getnframes() == 8000 + int(8000 * 0.4) + int(8000 * 0.3)
    assert _with_tone(b"not a wav") == b"not a wav"  # unknown audio is left alone


def test_wrong_key_reprompts_without_spending_a_no_input_retry(client, pending_execution, monkeypatch):
    """A real key press (just not 1/2) means the approver is on the line and responding -
    it must not count against the silent-timeout retry budget."""
    execution_id, _ = pending_execution
    params = _start_voice(client, monkeypatch, execution_id)
    params["action"] = "choice"
    for _ in range(5):  # far more than MAX_NO_INPUT_ATTEMPTS
        response = client.post("/api/webhooks/vobiz", query_string=params, data={"Digits": "9"})
        assert response.status_code == 200
        assert b"<Gather" in response.data
    assert get_service().get_execution(execution_id)["status"] == "WAITING_FOR_APPROVAL"


def test_repeated_silence_gives_up_cleanly_instead_of_looping_forever(client, pending_execution, monkeypatch):
    from services.voice_approval_service import MAX_NO_INPUT_ATTEMPTS

    execution_id, approval_id = pending_execution
    params = _start_voice(client, monkeypatch, execution_id)
    params["action"] = "choice"

    for attempt in range(1, MAX_NO_INPUT_ATTEMPTS + 1):
        response = client.post("/api/webhooks/vobiz", query_string=params, data={"Digits": ""})
        assert response.status_code == 200
        assert b"<Gather" in response.data, f"attempt {attempt} should still retry"

    final = client.post("/api/webhooks/vobiz", query_string=params, data={"Digits": ""})
    assert final.status_code == 200
    assert b"<Gather" not in final.data  # gives up instead of looping forever
    assert b"<Hangup" in final.data

    # Left PENDING (not decided) so web approval remains available.
    approval = get_service().select_one("approvals", {"id": approval_id})
    assert approval["status"] == "PENDING"
    assert get_service().get_execution(execution_id)["status"] == "WAITING_FOR_APPROVAL"


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
    monkeypatch.setattr(voice, "synthesize", lambda prompt, language_code="en-IN": b"RIFF-audio")
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
    params["action"] = "choice"
    params["token"] = "wrong"
    assert client.post("/api/webhooks/vobiz", query_string=params, data={"Digits": "1"}).status_code == 403
    assert get_service().get_execution(execution_id)["status"] == "WAITING_FOR_APPROVAL"


def test_speech_and_confirmation_callbacks_no_longer_exist(client, pending_execution, monkeypatch):
    """Only a key press can decide; the old record/confirm steps are rejected."""
    execution_id, _ = pending_execution
    params = _start_voice(client, monkeypatch, execution_id)
    for action in ("record", "confirm"):
        params["action"] = action
        response = client.post("/api/webhooks/vobiz", query_string=params,
                               data={"Digits": "1", "RecordingUrl": "https://api.vobiz.ai/recording.wav"})
        assert response.status_code == 403
    assert get_service().get_execution(execution_id)["status"] == "WAITING_FOR_APPROVAL"


def test_missed_call_can_be_retried(client, pending_execution, monkeypatch):
    execution_id, approval_id = pending_execution
    params = _start_voice(client, monkeypatch, execution_id)
    params["action"] = "hangup"
    assert client.post("/api/webhooks/vobiz", query_string=params).status_code == 200

    approval = get_service().select_one("approvals", {"id": approval_id})
    assert approval["status"] == "PENDING"
    assert approval["raw_response_json"]["voice_status"] == "ended"  # UI offers "Call again"
    _start_voice(client, monkeypatch, execution_id)  # a second call is allowed


def test_decision_made_elsewhere_during_call_ends_call_cleanly(client, pending_execution, monkeypatch):
    import services.voice_approval_service as voice
    from app import InvalidStateError

    execution_id, _ = pending_execution
    params = _start_voice(client, monkeypatch, execution_id)

    def already_decided(*args, **kwargs):
        raise InvalidStateError("Approval was already decided")

    monkeypatch.setattr(voice, "decide", already_decided)
    params["action"] = "choice"
    response = client.post("/api/webhooks/vobiz", query_string=params, data={"Digits": "1"})
    assert response.status_code == 200
    assert b"already decided" in response.data and b"<Hangup" in response.data


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
