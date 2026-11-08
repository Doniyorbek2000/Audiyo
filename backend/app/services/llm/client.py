"""LLM klienti (Google Gemini generateContent, JSON rejimi)."""
from __future__ import annotations

import json
import time
from typing import Any, Protocol

import httpx

from app.config import get_settings


MODEL_COOLDOWN_S = 300.0
_unavailable_until: dict[str, float] = {}  # jarayon boʻyicha umumiy: model → qachongacha chetlab oʻtiladi


class LLMError(RuntimeError):
    pass


class LLMNotConfigured(LLMError):
    pass


class ModelUnavailable(LLMError):
    pass


class LLMClient(Protocol):
    def generate_json(
        self, system: str, prompt: str, schema: dict[str, Any], temperature: float = 0.3
    ) -> Any: ...


class GeminiLLM:
    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        timeout: float = 120.0,
        max_retries: int = 4,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        s = get_settings()
        self.api_key = api_key or s.gemini_api_key
        if not self.api_key:
            raise LLMNotConfigured("GEMINI_API_KEY sozlanmagan — tarjima va atributsiya uchun kerak")
        self.models = [model] if model else [s.gemini_text_model, *s.gemini_text_fallback_models]
        self.model = self.models[0]
        self.base_url = (base_url or s.gemini_base_url).rstrip("/")
        self.max_retries = max_retries
        self._http = httpx.Client(timeout=timeout, transport=transport)

    def generate_json(
        self, system: str, prompt: str, schema: dict[str, Any], temperature: float = 0.3
    ) -> Any:
        """Asosiy model band (503) yoki yopilgan (404) boʻlsa — keyingi modelga oʻtadi.
        Band model MODEL_COOLDOWN_S davomida chetlab oʻtiladi (har soʻrovda qayta urinmaslik uchun)."""
        last: LLMError | None = None
        now = time.monotonic()
        ordered = [m for m in self.models if _unavailable_until.get(m, 0) <= now] or self.models
        for model in ordered:
            try:
                return self._generate(model, system, prompt, schema, temperature)
            except ModelUnavailable as exc:
                _unavailable_until[model] = time.monotonic() + MODEL_COOLDOWN_S
                last = exc
        raise last or LLMError("Gemini modellari mavjud emas")

    def _generate(
        self, model: str, system: str, prompt: str, schema: dict[str, Any], temperature: float
    ) -> Any:
        url = f"{self.base_url}/v1beta/models/{model}:generateContent"
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": temperature,
                "responseMimeType": "application/json",
                "responseSchema": schema,
            },
        }
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                resp = self._http.post(url, json=body, headers={"x-goog-api-key": self.api_key})
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = exc  # timeout yoki uzilgan ulanish — qayta urinish
            else:
                if resp.status_code == 200:
                    return self._parse(resp.json())
                last_error = LLMError(f"Gemini {model} {resp.status_code}: {resp.text[:300]}")
                if resp.status_code == 404:
                    raise ModelUnavailable(str(last_error))
                if resp.status_code not in (408, 429, 500, 502, 503, 504):
                    raise last_error
                if resp.status_code == 503 and attempt >= 1:
                    raise ModelUnavailable(str(last_error))  # band model — zaxiraga oʻtish
            time.sleep(min(30, 2**attempt))
        raise ModelUnavailable(f"Gemini {model} javob bermadi: {last_error}")

    @staticmethod
    def _parse(payload: dict[str, Any]) -> Any:
        try:
            candidate = payload["candidates"][0]
            text = "".join(p.get("text", "") for p in candidate["content"]["parts"])
        except (KeyError, IndexError) as exc:
            reason = payload.get("promptFeedback") or payload
            raise LLMError(f"Gemini boʻsh javob: {str(reason)[:300]}") from exc
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise LLMError(f"Gemini JSON emas: {text[:300]}") from exc


def get_llm() -> LLMClient:
    return GeminiLLM()
