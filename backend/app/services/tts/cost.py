"""TTS xarajatini hisoblash.

Formula (provayder p uchun):
    api_cost_usd(p) = chars / 1000 × usd_per_1k_chars(p) + audio_seconds × usd_per_second(p)
    customer_charge = api_cost_usd × platform_markup
Oldindan hisob (estimate) audio uzunligini bilmaydi, shuning uchun soʻnggi hadda
audio_seconds ≈ chars / 15 (oʻzbekcha oʻrtacha ~15 belgi/sekund) qabul qilinadi.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from app.config import Settings, get_settings
from app.models import TTSProvider

UZ_CHARS_PER_SECOND = 15.0
_Q = Decimal("0.0001")


@dataclass(frozen=True)
class ProviderPricing:
    usd_per_1k_chars: float
    usd_per_second: float = 0.0


def pricing(provider: TTSProvider | str, settings: Settings | None = None) -> ProviderPricing:
    s = settings or get_settings()
    p = TTSProvider(provider)
    if p is TTSProvider.ELEVENLABS:
        return ProviderPricing(s.elevenlabs_usd_per_1k_chars)
    return ProviderPricing(s.gemini_tts_usd_per_1k_chars, s.gemini_tts_usd_per_audio_second)


def api_cost(
    provider: TTSProvider | str, chars: int, audio_seconds: float = 0.0, settings: Settings | None = None
) -> Decimal:
    pr = pricing(provider, settings)
    value = Decimal(str(chars)) / 1000 * Decimal(str(pr.usd_per_1k_chars)) + Decimal(
        str(audio_seconds)
    ) * Decimal(str(pr.usd_per_second))
    return value.quantize(_Q, rounding=ROUND_HALF_UP)


def customer_charge(api_cost_usd: Decimal, settings: Settings | None = None) -> Decimal:
    s = settings or get_settings()
    return (api_cost_usd * Decimal(str(s.platform_markup))).quantize(_Q, rounding=ROUND_HALF_UP)


def estimate(
    chars_by_provider: dict[TTSProvider | str, int], settings: Settings | None = None
) -> tuple[Decimal, Decimal]:
    """(api_cost, customer_charge) — TTS boshlanishidan oldingi baho."""
    total = Decimal("0")
    for provider, chars in chars_by_provider.items():
        total += api_cost(provider, chars, chars / UZ_CHARS_PER_SECOND, settings)
    return total, customer_charge(total, settings)
