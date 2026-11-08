"""Ovoz profillari reyestri."""
import uuid

from fastapi import APIRouter, HTTPException, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import or_, select

from app.config import get_settings
from app.deps import SessionDep, UserDep
from app.models import AgeGroup, Gender, TTSProvider, VoiceProfile
from app.schemas import VoiceOut

router = APIRouter(prefix="/voices", tags=["voices"])


def _out(v: VoiceProfile) -> VoiceOut:
    o = VoiceOut.model_validate(v)
    o.is_system = v.user_id is None
    return o


@router.get("", response_model=list[VoiceOut])
async def list_voices(user: UserDep, session: SessionDep, provider: TTSProvider | None = None) -> list[VoiceOut]:
    s = get_settings()
    enabled = [p for p, key in ((TTSProvider.ELEVENLABS, s.elevenlabs_api_key), (TTSProvider.GEMINI, s.gemini_api_key)) if key]
    q = select(VoiceProfile).where(or_(VoiceProfile.user_id.is_(None), VoiceProfile.user_id == user.id))
    if provider:
        q = q.where(VoiceProfile.provider == provider)
    elif enabled:
        q = q.where(VoiceProfile.provider.in_(enabled))
    rows = (await session.scalars(q.order_by(VoiceProfile.provider, VoiceProfile.name))).all()
    return [_out(v) for v in rows]


_GENDER = {"male": Gender.MALE, "female": Gender.FEMALE}
_AGE = {"young": AgeGroup.YOUNG_ADULT, "middle_aged": AgeGroup.ADULT, "middle aged": AgeGroup.ADULT,
        "old": AgeGroup.ELDERLY, "child": AgeGroup.CHILD}


@router.post("/sync", response_model=list[VoiceOut])
async def sync_elevenlabs(user: UserDep, session: SessionDep) -> list[VoiceOut]:
    """ElevenLabs hisobidagi ovozlarni (shu jumladan klonlanganlarni) foydalanuvchi reyestriga qoʻshadi."""
    if not get_settings().elevenlabs_api_key:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "ElevenLabs sozlanmagan")
    from app.services.tts.elevenlabs import ElevenLabsClient

    voices = await run_in_threadpool(ElevenLabsClient().list_voices)
    existing = set((await session.scalars(select(VoiceProfile.provider_voice_id).where(
        VoiceProfile.provider == TTSProvider.ELEVENLABS,
        or_(VoiceProfile.user_id.is_(None), VoiceProfile.user_id == user.id)))).all())
    added = []
    for v in voices:
        if v.get("voice_id") in existing:
            continue
        labels = v.get("labels") or {}
        vp = VoiceProfile(
            id=uuid.uuid4(), user_id=user.id, name=(v.get("name") or "Ovoz")[:100], provider=TTSProvider.ELEVENLABS,
            provider_voice_id=v["voice_id"], gender=_GENDER.get(str(labels.get("gender", "")).lower(), Gender.UNKNOWN),
            age_group=_AGE.get(str(labels.get("age", "")).lower(), AgeGroup.ADULT),
            is_cloned=v.get("category") in ("cloned", "professional"),
            description=(v.get("description") or labels.get("description") or "")[:500] or None,
        )
        session.add(vp)
        added.append(vp)
    await session.commit()
    return [_out(v) for v in added]


@router.delete("/{voice_id}", status_code=204)
async def delete_voice(voice_id: uuid.UUID, user: UserDep, session: SessionDep) -> None:
    v = await session.get(VoiceProfile, voice_id)
    if v is None or v.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ovoz topilmadi (tizim ovozlarini oʻchirib boʻlmaydi)")
    await session.delete(v)
    await session.commit()
