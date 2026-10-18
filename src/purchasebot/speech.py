"""Voice notes -> text with Sarvam AI (built for Hindi and other Indian languages).

Site engineers will send voice notes. Sarvam's REST endpoint is meant for
short clips (~30 s), so longer notes are cut into 25 s pieces with ffmpeg.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Protocol

import httpx

log = logging.getLogger(__name__)

SARVAM_STT_URL = "https://api.sarvam.ai/speech-to-text"

# Biases recognition toward construction vocabulary (saaras:v4 supports up to 50).
KEYTERMS = [
    "cement", "OPC", "PPC", "TMT", "sariya", "gitti", "rodi", "balu", "reti", "sand", "aggregate", "brick",
    "eent", "binding wire", "shuttering", "plywood", "bags", "brass", "cft", "kg", "ton", "Fe500", "12 mm",
    "16 mm", "8 mm", "10 mm", "20 mm", "PVC pipe", "GI pipe", "paint", "primer", "nails", "kil", "tiles",
    "waterproofing", "diesel", "mixer", "vibrator", "Nicobar", "Kamorta", "Diglipur", "Abbas", "urgent",
]


class SpeechError(Exception):
    pass


class Speech(Protocol):
    def transcribe(self, audio: bytes, mime: str) -> str: ...


class SarvamSpeech:
    def __init__(self, api_key: str, model: str = "saaras:v4", timeout: float = 60.0):
        self.api_key = api_key
        self.model = model
        self.http = httpx.Client(timeout=timeout)

    def _post(self, audio: bytes, filename: str, mime: str) -> httpx.Response:
        data = {"model": self.model, "language_code": "unknown"}
        if self.model.startswith("saaras:v4"):
            data["keyterms"] = json.dumps(KEYTERMS)
        headers = {"api-subscription-key": self.api_key} if self.api_key else {}
        return self.http.post(SARVAM_STT_URL, headers=headers, data=data, files={"file": (filename, audio, mime)})

    def transcribe(self, audio: bytes, mime: str) -> str:
        mime = (mime or "audio/ogg").split(";")[0]
        ext = {"audio/ogg": "ogg", "audio/opus": "opus", "audio/mpeg": "mp3", "audio/mp4": "m4a",
               "audio/aac": "aac", "audio/amr": "amr", "audio/wav": "wav"}.get(mime, "ogg")
        r = self._post(audio, f"voice.{ext}", mime)
        if r.status_code == 200:
            return r.json().get("transcript", "").strip()
        log.info("Sarvam returned %s (%s); trying in 25s chunks", r.status_code, r.text[:200])
        if r.status_code in (401, 403):
            raise SpeechError("Sarvam API key rejected")
        return self._transcribe_chunked(audio, ext)

    def _transcribe_chunked(self, audio: bytes, ext: str) -> str:
        if not shutil.which("ffmpeg"):
            raise SpeechError("Voice note too long and ffmpeg is not installed to split it")
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / f"in.{ext}"
            src.write_bytes(audio)
            subprocess.run(
                ["ffmpeg", "-loglevel", "error", "-i", str(src), "-f", "segment", "-segment_time", "25",
                 "-ac", "1", "-ar", "16000", str(Path(tmp) / "part%03d.wav")],
                check=True, timeout=120,
            )
            pieces = []
            for part in sorted(Path(tmp).glob("part*.wav")):
                r = self._post(part.read_bytes(), part.name, "audio/wav")
                if r.status_code != 200:
                    raise SpeechError(f"Sarvam error {r.status_code}: {r.text[:200]}")
                pieces.append(r.json().get("transcript", "").strip())
        return " ".join(p for p in pieces if p)


class NoSpeech:
    def transcribe(self, audio: bytes, mime: str) -> str:
        raise SpeechError("Voice notes are not set up (SARVAM_API_KEY missing)")
