"""Kredit hisobi: bonus, toʻldirish, TTS oldidan rezerv (HOLD) va yakuniy hisob-kitob (SETTLE).

Barcha balans oʻzgarishlari bitta atomik UPDATE ... RETURNING orqali bajariladi va har biri
`transactions` jadvalida balance_after_usd bilan qayd etiladi.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import Transaction, TransactionKind, User

ZERO = Decimal("0")


class InsufficientCredits(Exception):
    def __init__(self, required: Decimal, balance: Decimal):
        super().__init__(f"Kredit yetarli emas: kerak ${required:.4f}, balans ${balance:.4f}")
        self.required = required
        self.balance = balance


class DuplicatePayment(Exception):
    pass


def balance(session: Session, user_id: uuid.UUID) -> Decimal:
    return session.execute(select(User.credit_balance_usd).where(User.id == user_id)).scalar_one()


def _apply(
    session: Session,
    user_id: uuid.UUID,
    amount: Decimal,
    kind: TransactionKind,
    *,
    allow_negative: bool = False,
    media_project_id: uuid.UUID | None = None,
    book_project_id: uuid.UUID | None = None,
    payment_id: str | None = None,
    description: str | None = None,
) -> Transaction:
    stmt = update(User).where(User.id == user_id)
    if amount < 0 and not allow_negative:
        stmt = stmt.where(User.credit_balance_usd + amount >= 0)
    row = session.execute(
        stmt.values(credit_balance_usd=User.credit_balance_usd + amount).returning(User.credit_balance_usd)
    ).first()
    if row is None:
        raise InsufficientCredits(-amount, balance(session, user_id))
    tx = Transaction(
        user_id=user_id,
        kind=kind,
        amount_usd=amount,
        balance_after_usd=row[0],
        media_project_id=media_project_id,
        book_project_id=book_project_id,
        payment_id=payment_id,
        description=description,
    )
    session.add(tx)
    session.flush()
    return tx


def grant_bonus(session: Session, user_id: uuid.UUID, amount: Decimal, description: str) -> Transaction:
    return _apply(session, user_id, amount, TransactionKind.BONUS, description=description)


def topup(session: Session, user_id: uuid.UUID, amount: Decimal, payment_id: str, description: str | None = None) -> Transaction:
    if amount <= 0:
        raise ValueError("Toʻlov summasi musbat boʻlishi kerak")
    exists = session.execute(select(Transaction.id).where(Transaction.payment_id == payment_id)).first()
    if exists:
        raise DuplicatePayment(payment_id)
    return _apply(session, user_id, amount, TransactionKind.TOPUP, payment_id=payment_id,
                  description=description or "Balansni toʻldirish")


def hold(
    session: Session,
    user_id: uuid.UUID,
    amount: Decimal,
    *,
    media_project_id: uuid.UUID | None = None,
    book_project_id: uuid.UUID | None = None,
) -> Transaction:
    """TTS boshlanishidan oldin taxminiy summani band qilish."""
    return _apply(
        session, user_id, -amount, TransactionKind.HOLD,
        media_project_id=media_project_id, book_project_id=book_project_id,
        description="TTS uchun kredit rezervi",
    )


def settle(
    session: Session,
    user_id: uuid.UUID,
    held: Decimal,
    actual: Decimal,
    *,
    media_project_id: uuid.UUID | None = None,
    book_project_id: uuid.UUID | None = None,
) -> Transaction | None:
    """Haqiqiy sarf boʻyicha yakunlash: ortiqcha rezerv qaytariladi, yetmagani yechiladi."""
    delta = held - actual
    if delta == 0:
        return None
    return _apply(
        session, user_id, delta, TransactionKind.SETTLE,
        allow_negative=True,  # xizmat allaqachon koʻrsatilgan
        media_project_id=media_project_id, book_project_id=book_project_id,
        description=f"Yakuniy hisob: rezerv ${held:.4f}, sarf ${actual:.4f}",
    )
