"""Vobiz outbound call transport."""

import requests

from config import Config

TIMEOUT = (3, 10)


class VobizError(Exception):
    """Vobiz call request failed."""


def place_approval_call(answer_url: str, hangup_url: str, to_number: str) -> str:
    """Ask Vobiz to dial to_number (resolved by approver_service). Returns the call ID."""
    if not Config.voice_call_configured():
        raise VobizError("Vobiz requires auth ID, auth token, caller ID, and public HTTPS URL")
    if not to_number:
        raise VobizError("No approver number to call")
    try:
        response = requests.post(
            f"https://api.vobiz.ai/api/v1/Account/{Config.VOBIZ_AUTH_ID}/Call/",
            headers={
                "X-Auth-ID": Config.VOBIZ_AUTH_ID,
                "X-Auth-Token": Config.VOBIZ_AUTH_TOKEN,
            },
            json={
                "from": Config.VOBIZ_FROM_NUMBER,
                "to": to_number,
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

