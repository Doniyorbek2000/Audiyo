"""Ishchilar uchun umumiy yordamchilar."""
from __future__ import annotations

import shutil
import uuid
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path

from app import events
from app.config import get_settings
from app.db import sync_session
from app.models import BookProject, BookStatus, MediaProject, ProjectStatus
from app.state_machine import BOOK_PROGRESS, PROJECT_PROGRESS


@contextmanager
def workdir(kind: str, entity_id: uuid.UUID | str):
    path = Path(get_settings().work_dir) / kind / f"{entity_id}-{uuid.uuid4().hex[:8]}"
    path.mkdir(parents=True, exist_ok=True)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def project_stage(project_id: uuid.UUID, stage: str, message: str, progress: float | None = None) -> None:
    events.publish("project", project_id, "progress", stage=stage, message=message, progress=progress)


def set_project_status(project_id: uuid.UUID, status: ProjectStatus, message: str | None = None) -> None:
    progress = PROJECT_PROGRESS.get(status, 0)
    with sync_session() as s:
        p = s.get(MediaProject, project_id)
        p.status = status
        p.progress = Decimal(progress)
        p.error_message = None
    events.publish("project", project_id, "status", status=status.value, progress=progress, message=message)


def fail_project(project_id: uuid.UUID, error: str) -> None:
    with sync_session() as s:
        p = s.get(MediaProject, project_id)
        if p:
            p.status = ProjectStatus.FAILED
            p.error_message = error[:4000]
    events.publish("project", project_id, "error", status=ProjectStatus.FAILED.value, message=error[:1000])


def book_stage(book_id: uuid.UUID, stage: str, message: str, progress: float | None = None) -> None:
    events.publish("book", book_id, "progress", stage=stage, message=message, progress=progress)


def set_book_status(book_id: uuid.UUID, status: BookStatus, message: str | None = None) -> None:
    progress = BOOK_PROGRESS.get(status, 0)
    with sync_session() as s:
        b = s.get(BookProject, book_id)
        b.status = status
        b.progress = Decimal(progress)
        b.error_message = None
    events.publish("book", book_id, "status", status=status.value, progress=progress, message=message)


def fail_book(book_id: uuid.UUID, error: str) -> None:
    with sync_session() as s:
        b = s.get(BookProject, book_id)
        if b:
            b.status = BookStatus.FAILED
            b.error_message = error[:4000]
    events.publish("book", book_id, "error", status=BookStatus.FAILED.value, message=error[:1000])


def interpolate(start: float, end: float, fraction: float) -> float:
    return round(start + (end - start) * max(0.0, min(1.0, fraction)), 2)
