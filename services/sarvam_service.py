"""Small REST wrapper for Sarvam speech services."""

import base64
import binascii
from pathlib import PurePosixPath

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


def transcribe(audio: bytes, filename: str = "response.wav") -> str:
    """Translate short English or Indic speech into English for deterministic parsing."""
    if not Config.SARVAM_API_KEY:
        raise SarvamError("Sarvam is not configured")
    if not audio or len(audio) > 2_000_000:
        raise SarvamError("Recording is empty or too large")
    extension = PurePosixPath(filename).suffix.lower()
    content_type = "audio/mpeg" if extension == ".mp3" else "audio/wav"
    try:
        response = requests.post(
            f"{SARVAM_BASE_URL}/speech-to-text",
            headers={"api-subscription-key": Config.SARVAM_API_KEY},
            files={"file": (filename, audio, content_type)},
            data={"model": "saaras:v3", "mode": "translate"},
            timeout=TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
        transcript = data.get("transcript") if isinstance(data, dict) else None
        if not isinstance(transcript, str) or not transcript.strip():
            raise SarvamError("Sarvam STT returned no transcript")
        return transcript.strip()
    except (requests.RequestException, ValueError, KeyError) as exc:
        raise SarvamError("Sarvam STT request failed") from exc
