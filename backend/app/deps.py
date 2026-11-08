"""FastAPI bogʻliqliklari."""
import uuid
from typing import Annotated

from fastapi import Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import BookProject, MediaProject, User
from app.security import decode_access_token

SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def current_user(
    request: Request,
    session: SessionDep,
    token: Annotated[str | None, Query(include_in_schema=False)] = None,
) -> User:
    """Bearer token sarlavhadan yoki ?token= (EventSource/SSE uchun) olinadi."""
    raw = None
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        raw = auth[7:]
    elif token:
        raw = token
    user_id = decode_access_token(raw) if raw else None
    if user_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Avtorizatsiya talab qilinadi",
                            headers={"WWW-Authenticate": "Bearer"})
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Foydalanuvchi topilmadi")
    return user


UserDep = Annotated[User, Depends(current_user)]


async def get_project(project_id: uuid.UUID, user: UserDep, session: SessionDep) -> MediaProject:
    p = await session.get(MediaProject, project_id)
    if p is None or p.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Loyiha topilmadi")
    return p


async def get_book(book_id: uuid.UUID, user: UserDep, session: SessionDep) -> BookProject:
    b = await session.get(BookProject, book_id)
    if b is None or b.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Kitob topilmadi")
    return b


ProjectDep = Annotated[MediaProject, Depends(get_project)]
BookDep = Annotated[BookProject, Depends(get_book)]
