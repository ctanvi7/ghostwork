"""Vobiz outbound call transport and safe recording retrieval."""

from urllib.parse import urlparse

import requests

from config import Config

TIMEOUT = (3, 10)


class VobizError(Exception):
    """Vobiz call or recording operation failed."""


def place_approval_call(answer_url: str, hangup_url: str) -> str:
    if not Config.voice_call_configured():
        raise VobizError("Vobiz requires auth ID, auth token, phone numbers, and public HTTPS URL")
    try:
        response = requests.post(
            f"https://api.vobiz.ai/api/v1/Account/{Config.VOBIZ_AUTH_ID}/Call/",
            headers={
                "X-Auth-ID": Config.VOBIZ_AUTH_ID,
                "X-Auth-Token": Config.VOBIZ_AUTH_TOKEN,
            },
            json={
                "from": Config.VOBIZ_FROM_NUMBER,
                "to": Config.APPROVER_PHONE,
                "answer_url": answer_url,
                "answer_method": "POST",
                "hangup_url": hangup_url,
                "hangup_method": "POST",
            },
            timeout=TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
        call_id = (data.get("request_uuid") or data.get("call_uuid")) if isinstance(data, dict) else None
        if not isinstance(call_id, str) or not call_id:
            raise VobizError("Vobiz returned no call ID")
        return call_id
    except (requests.RequestException, ValueError) as exc:
        raise VobizError("Vobiz call request failed") from exc


def fetch_recording(recording_url: str) -> bytes:
    """Fetch only from documented Vobiz/S3 hosts; never follow redirects."""
    parsed = urlparse(recording_url)
    host = (parsed.hostname or "").lower()
    allowed = host == "api.vobiz.ai" or host == "s3.amazonaws.com" or host.endswith(".s3.amazonaws.com")
    if parsed.scheme != "https" or not allowed or parsed.username or parsed.password:
        raise VobizError("Recording URL is not trusted")
    try:
        response = requests.get(recording_url, timeout=TIMEOUT, allow_redirects=False)
        if 300 <= response.status_code < 400:
            raise VobizError("Recording redirect is not allowed")
        response.raise_for_status()
        if len(response.content) > 2_000_000 or not response.content:
            raise VobizError("Recording is empty or too large")
        return response.content
    except requests.RequestException as exc:
        raise VobizError("Could not download Vobiz recording") from exc
