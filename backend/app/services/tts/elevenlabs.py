"""ElevenLabs Multilingual v2 klienti (TTS, ovoz klonlash, ovozlar roʻyxati)."""
from __future__ import annotations

from pathlib import Path

import httpx

from app.config import get_settings
from app.services.text.pauses import render_inline_pauses_ssml
from app.services.tts.base import (
    ELEVENLABS_EMOTION_SETTINGS,
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


class ElevenLabsClient:
    name = "elevenlabs"

    def __init__(
        self,
        api_key: str | None = None,
        model_id: str | None = None,
        base_url: str | None = None,
        timeout: float | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        s = get_settings()
        self.api_key = api_key or s.elevenlabs_api_key
        self.model_id = model_id or s.elevenlabs_model_id
        self.base_url = (base_url or s.elevenlabs_base_url).rstrip("/")
        self._http = httpx.Client(timeout=timeout or s.tts_timeout_seconds, transport=transport)

    def _headers(self) -> dict[str, str]:
        if not self.api_key:
            raise ProviderNotConfigured("ELEVENLABS_API_KEY sozlanmagan")
        return {"xi-api-key": self.api_key, "accept": "audio/mpeg"}

    @staticmethod
    def _raise_for(resp: httpx.Response) -> None:
        if resp.status_code < 400:
            return
        try:
            detail = resp.json().get("detail", {})
        except ValueError:
            detail = {}
        status = detail.get("status", "") if isinstance(detail, dict) else ""
        message = (detail.get("message") if isinstance(detail, dict) else str(detail)) or resp.text[:300]
        if status in ("quota_exceeded", "insufficient_credits") or resp.status_code == 402:
            raise QuotaExceeded(f"ElevenLabs kvotasi tugadi: {message}")
        if resp.status_code == 401:
            raise AuthError(f"ElevenLabs avtorizatsiya xatosi: {message}")
        if resp.status_code == 429:
            raise RateLimited(f"ElevenLabs: {message}")
        if resp.status_code >= 500:
            raise ProviderUnavailable(f"ElevenLabs {resp.status_code}: {message}")
        raise BadRequest(f"ElevenLabs {resp.status_code}: {message}")

    def synthesize(self, request: TTSRequest) -> TTSResult:
        settings = dict(ELEVENLABS_EMOTION_SETTINGS.get(request.emotion, ELEVENLABS_EMOTION_SETTINGS["neutral"]))
        settings["use_speaker_boost"] = True
        if request.speed != 1.0:
            settings["speed"] = max(0.7, min(1.2, request.speed))
        body = {
            "text": render_inline_pauses_ssml(request.text),
            "model_id": self.model_id,
            "voice_settings": settings,
        }
        try:
            resp = self._http.post(
                f"{self.base_url}/v1/text-to-speech/{request.voice_id}",
                params={"output_format": "mp3_44100_128"},
                json=body,
                headers=self._headers(),
            )
        except httpx.TimeoutException as exc:
            raise ProviderTimeout(f"ElevenLabs vaqt tugadi: {exc}") from exc
        except httpx.TransportError as exc:
            raise ProviderUnavailable(f"ElevenLabs tarmoq xatosi: {exc}") from exc
        self._raise_for(resp)
        return TTSResult(audio=resp.content, extension="mp3", characters=len(request.text))

    def clone_voice(self, name: str, sample_paths: list[Path], description: str = "") -> str:
        """Instant Voice Cloning: namunalardan yangi ovoz yaratadi, voice_id qaytaradi."""
        files = [("files", (p.name, p.read_bytes(), "audio/mpeg")) for p in sample_paths]
        headers = {k: v for k, v in self._headers().items() if k != "accept"}
        try:
            resp = self._http.post(
                f"{self.base_url}/v1/voices/add",
                data={"name": name, "description": description, "remove_background_noise": "true"},
                files=files,
                headers=headers,
                timeout=180,
            )
        except httpx.TimeoutException as exc:
            raise ProviderTimeout(str(exc)) from exc
        self._raise_for(resp)
        return resp.json()["voice_id"]

    def list_voices(self) -> list[dict]:
        headers = {k: v for k, v in self._headers().items() if k != "accept"}
        resp = self._http.get(f"{self.base_url}/v1/voices", headers=headers)
        self._raise_for(resp)
        return resp.json().get("voices", [])
