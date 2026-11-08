"""Google Gemini TTS klienti (generateContent, AUDIO modalligi)."""
from __future__ import annotations

import base64
import io
import re
import wave

import httpx

from app.config import get_settings
from app.services.tts.base import (
    GEMINI_EMOTION_STYLE,
    AuthError,
    BadRequest,
    ProviderNotConfigured,
    ProviderTimeout,
    ProviderUnavailable,
    QuotaExceeded,
    RateLimited,
    TTSRequest,
    TTSResult,
)

DEFAULT_SAMPLE_RATE = 24000


def pcm_to_wav(pcm: bytes, sample_rate: int = DEFAULT_SAMPLE_RATE, channels: int = 1) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)
    return buf.getvalue()


class GeminiTTSClient:
    name = "gemini"

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        timeout: float | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        s = get_settings()
        self.api_key = api_key or s.gemini_api_key
        self.model = model or s.gemini_tts_model
        self.base_url = (base_url or s.gemini_base_url).rstrip("/")
        self._http = httpx.Client(timeout=timeout or s.tts_timeout_seconds, transport=transport)

    @staticmethod
    def build_prompt(request: TTSRequest) -> str:
        style = GEMINI_EMOTION_STYLE.get(request.emotion, GEMINI_EMOTION_STYLE["neutral"])
        if request.speed > 1.05:
            style += ", at a slightly faster pace"
        elif request.speed < 0.95:
            style += ", at a slightly slower pace"
        return f"{style}:\n{request.text}"

    @staticmethod
    def _raise_for(resp: httpx.Response) -> None:
        if resp.status_code < 400:
            return
        try:
            err = resp.json().get("error", {})
        except ValueError:
            err = {}
        status = err.get("status", "")
        message = err.get("message") or resp.text[:300]
        if resp.status_code == 429 or status == "RESOURCE_EXHAUSTED":
            # Kunlik kvota vs daqiqalik limit
            if re.search(r"quota|billing|per day|exceeded your current quota", message, re.I):
                raise QuotaExceeded(f"Gemini kvotasi tugadi: {message}")
            raise RateLimited(f"Gemini: {message}")
        if resp.status_code in (401, 403):
            raise AuthError(f"Gemini avtorizatsiya xatosi: {message}")
        if resp.status_code >= 500:
            raise ProviderUnavailable(f"Gemini {resp.status_code}: {message}")
        raise BadRequest(f"Gemini {resp.status_code}: {message}")

    def synthesize(self, request: TTSRequest) -> TTSResult:
        if not self.api_key:
            raise ProviderNotConfigured("GEMINI_API_KEY sozlanmagan")
        body = {
            "contents": [{"role": "user", "parts": [{"text": self.build_prompt(request)}]}],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": request.voice_id}}},
            },
        }
        try:
            resp = self._http.post(
                f"{self.base_url}/v1beta/models/{self.model}:generateContent",
                json=body,
                headers={"x-goog-api-key": self.api_key},
            )
        except httpx.TimeoutException as exc:
            raise ProviderTimeout(f"Gemini vaqt tugadi: {exc}") from exc
        except httpx.TransportError as exc:
            raise ProviderUnavailable(f"Gemini tarmoq xatosi: {exc}") from exc
        self._raise_for(resp)
        payload = resp.json()
        try:
            part = next(
                p for p in payload["candidates"][0]["content"]["parts"] if "inlineData" in p
            )["inlineData"]
        except (KeyError, IndexError, StopIteration) as exc:
            raise ProviderUnavailable(f"Gemini audio qaytarmadi: {str(payload)[:300]}") from exc
        pcm = base64.b64decode(part["data"])
        rate_match = re.search(r"rate=(\d+)", part.get("mimeType", ""))
        rate = int(rate_match.group(1)) if rate_match else DEFAULT_SAMPLE_RATE
        return TTSResult(
            audio=pcm_to_wav(pcm, rate),
            extension="wav",
            characters=len(request.text),
            duration_seconds=len(pcm) / (2 * rate),
        )
