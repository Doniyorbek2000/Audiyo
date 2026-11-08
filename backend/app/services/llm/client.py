"""LLM klienti (Google Gemini generateContent, JSON rejimi)."""
from __future__ import annotations

import json
import time
from typing import Any, Protocol

import httpx

from app.config import get_settings


class LLMError(RuntimeError):
    pass


class LLMNotConfigured(LLMError):
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
        self.model = model or s.gemini_text_model
        self.base_url = (base_url or s.gemini_base_url).rstrip("/")
        self.max_retries = max_retries
        self._http = httpx.Client(timeout=timeout, transport=transport)

    def generate_json(
        self, system: str, prompt: str, schema: dict[str, Any], temperature: float = 0.3
    ) -> Any:
        url = f"{self.base_url}/v1beta/models/{self.model}:generateContent"
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
            except httpx.TimeoutException as exc:
                last_error = exc
            else:
                if resp.status_code == 200:
                    return self._parse(resp.json())
                last_error = LLMError(f"Gemini {resp.status_code}: {resp.text[:300]}")
                if resp.status_code not in (408, 429, 500, 502, 503, 504):
                    raise last_error
            time.sleep(min(30, 2**attempt))
        raise LLMError(f"Gemini javob bermadi: {last_error}")

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
