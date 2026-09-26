"""Small REST wrapper for Sarvam text-to-speech and translation (approval call prompts)."""

import base64
import binascii

import requests

from config import Config

SARVAM_BASE_URL = "https://api.sarvam.ai"
TIMEOUT = (3, 12)


class SarvamError(Exception):
    """Speech service is unavailable or returned invalid data."""


def synthesize(text: str, language_code: str = "en-IN") -> bytes:
    """Return WAV audio for a short approval prompt."""
    if not Config.SARVAM_API_KEY:
        raise SarvamError("Sarvam is not configured")
    try:
        response = requests.post(
            f"{SARVAM_BASE_URL}/text-to-speech",
            headers={"api-subscription-key": Config.SARVAM_API_KEY},
            json={
                "text": text,
                "language_code": language_code,
                "model": "bulbul:v3",
                "output_audio_codec": "wav",
                "speech_sample_rate": 8000,
            },
            timeout=TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
        audios = data.get("audios") if isinstance(data, dict) else None
        if not isinstance(audios, list) or not audios or not isinstance(audios[0], str):
            raise SarvamError("Sarvam TTS returned no audio")
        audio = base64.b64decode(audios[0], validate=True)
        if not audio or len(audio) > 5_000_000:
            raise SarvamError("Sarvam TTS returned invalid audio")
        return audio
    except (requests.RequestException, ValueError, KeyError, binascii.Error) as exc:
        raise SarvamError("Sarvam TTS request failed") from exc


def translate(text: str, target_language_code: str, source_language_code: str = "en-IN") -> str:
    """Translate a short prompt (e.g. English -> Hindi) so TTS can speak it natively."""
    if target_language_code == source_language_code:
        return text
    if not Config.SARVAM_API_KEY:
        raise SarvamError("Sarvam is not configured")
    try:
        response = requests.post(
            f"{SARVAM_BASE_URL}/translate",
            headers={"api-subscription-key": Config.SARVAM_API_KEY},
            json={
                "input": text,
                "source_language_code": source_language_code,
                "target_language_code": target_language_code,
                "model": "sarvam-translate:v1",
            },
            timeout=TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
        translated = data.get("translated_text") if isinstance(data, dict) else None
        if not isinstance(translated, str) or not translated.strip():
            raise SarvamError("Sarvam translate returned no text")
        return translated.strip()
    except (requests.RequestException, ValueError, KeyError) as exc:
        raise SarvamError("Sarvam translate request failed") from exc

