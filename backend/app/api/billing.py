"""Balans, tranzaksiyalar, provayderlar boʻyicha sarf va toʻlov webhooki."""
import hashlib
import hmac
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Query, Request, status
from sqlalchemy import case, func, select

from app.config import get_settings
from app.deps import SessionDep, UserDep
from app.models import Transaction, TTSJob, TTSJobStatus
from app.schemas import TopupIn, TransactionOut, UsageOut, UsageRow, UserOut, WebhookIn
from app.services import billing
from app.services.tts.cost import customer_charge

router = APIRouter(prefix="/billing", tags=["billing"])


@router.get("/balance", response_model=UserOut)
async def balance(user: UserDep, session: SessionDep):
    await session.refresh(user)
    return user


@router.get("/transactions", response_model=list[TransactionOut])
async def transactions(
    user: UserDep, session: SessionDep,
    offset: Annotated[int, Query(ge=0)] = 0, limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[Transaction]:
    q = (select(Transaction).where(Transaction.user_id == user.id)
         .order_by(Transaction.created_at.desc()).offset(offset).limit(limit))
    return list((await session.scalars(q)).all())


@router.get("/usage", response_model=UsageOut)
async def usage(user: UserDep, session: SessionDep, days: Annotated[int, Query(ge=1, le=365)] = 30) -> UsageOut:
    since = func.now() - func.make_interval(0, 0, 0, days)
    rows = (await session.execute(
        select(
            TTSJob.provider_name,
            func.count(),
            func.sum(case((TTSJob.status == TTSJobStatus.FAILED, 1), else_=0)),
            func.coalesce(func.sum(TTSJob.token_character_count), 0),
            func.coalesce(func.sum(TTSJob.audio_seconds), 0),
            func.coalesce(func.sum(TTSJob.api_cost_usd), 0),
            func.coalesce(func.avg(TTSJob.execution_latency_ms), 0),
            func.sum(case((TTSJob.fallback_from.is_not(None), 1), else_=0)),
        ).where(TTSJob.user_id == user.id, TTSJob.created_at >= since).group_by(TTSJob.provider_name)
    )).all()
    out = [UsageRow(provider=r[0], jobs=r[1], failed=int(r[2] or 0), characters=int(r[3]), audio_seconds=float(r[4]),
                    api_cost_usd=Decimal(r[5]), avg_latency_ms=float(r[6]), fallbacks=int(r[7] or 0)) for r in rows]
    total = sum((r.api_cost_usd for r in out), Decimal("0"))
    return UsageOut(rows=out, total_api_cost_usd=total, total_charge_usd=customer_charge(total))


@router.post("/topup/dev", response_model=TransactionOut, include_in_schema=False)
async def dev_topup(body: TopupIn, user: UserDep, session: SessionDep):
    """Faqat development muhitida: test uchun balansni toʻldirish."""
    if get_settings().environment != "development":
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    import uuid

    tx = await session.run_sync(lambda s: billing.topup(s, user.id, body.amount_usd, f"dev-{uuid.uuid4()}",
                                                        "Test toʻldirish"))
    await session.commit()
    return tx


@router.post("/webhook", status_code=204)
async def payment_webhook(request: Request, session: SessionDep,
                          x_signature: Annotated[str | None, Header()] = None) -> None:
    """Toʻlov provayderi (Payme/Click/Stripe adapteri) uchun umumiy webhook.
    Tana HMAC-SHA256 (PAYMENT_WEBHOOK_SECRET) bilan imzolangan boʻlishi kerak: X-Signature: <hex>."""
    secret = get_settings().payment_webhook_secret
    raw = await request.body()
    if not secret or not x_signature:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Imzo yoʻq")
    expected = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, x_signature):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Imzo notoʻgʻri")
    body = WebhookIn.model_validate_json(raw)
    if body.status.lower() not in ("paid", "success", "succeeded", "completed"):
        return
    try:
        await session.run_sync(lambda s: billing.topup(s, body.user_id, body.amount_usd, body.payment_id))
        await session.commit()
    except billing.DuplicatePayment:
        await session.rollback()  # idempotent: qayta yuborilgan webhook
