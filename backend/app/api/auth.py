from decimal import Decimal

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select

from app.config import get_settings
from app.deps import SessionDep, UserDep
from app.models import User
from app.schemas import LoginIn, RegisterIn, TokenOut, UserOut
from app.security import create_access_token, hash_password, verify_password
from app.services import billing

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenOut, status_code=201)
async def register(body: RegisterIn, session: SessionDep) -> TokenOut:
    email = body.email.lower()
    exists = await session.scalar(select(User.id).where(func.lower(User.email) == email))
    if exists:
        raise HTTPException(status.HTTP_409_CONFLICT, "Bu email allaqachon roʻyxatdan oʻtgan")
    user = User(email=email, password_hash=hash_password(body.password), full_name=body.full_name,
                credit_balance_usd=Decimal("0"))
    session.add(user)
    await session.flush()
    bonus = Decimal(str(get_settings().signup_bonus_usd))
    if bonus > 0:
        await session.run_sync(lambda s: billing.grant_bonus(s, user.id, bonus, "Roʻyxatdan oʻtish bonusi"))
    await session.commit()
    return TokenOut(access_token=create_access_token(user.id))


@router.post("/login", response_model=TokenOut)
async def login(body: LoginIn, session: SessionDep) -> TokenOut:
    user = await session.scalar(select(User).where(func.lower(User.email) == body.email.lower()))
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Email yoki parol notoʻgʻri")
    return TokenOut(access_token=create_access_token(user.id))


@router.get("/me", response_model=UserOut)
async def me(user: UserDep, session: SessionDep) -> User:
    await session.refresh(user)
    return user
