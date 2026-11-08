"""Video va kitob loyihalari uchun holat mashinalari."""
from app.models import BookStatus, ProjectStatus

PROJECT_FLOW: list[ProjectStatus] = [
    ProjectStatus.UPLOADED,
    ProjectStatus.STEM_SEPARATION,
    ProjectStatus.TRANSCRIBED,
    ProjectStatus.TRANSLATED,
    ProjectStatus.TTS_DISPATCHED,
    ProjectStatus.TIMING_ALIGNED,
    ProjectStatus.MASTERED,
    ProjectStatus.READY_FOR_EXPORT,
]

BOOK_FLOW: list[BookStatus] = [
    BookStatus.UPLOADED,
    BookStatus.PARSED,
    BookStatus.NORMALIZED,
    BookStatus.SEGMENTED,
    BookStatus.ATTRIBUTED,
    BookStatus.LEXICON_APPLIED,
    BookStatus.TTS_DISPATCHED,
    BookStatus.STITCHED,
    BookStatus.READY_FOR_EXPORT,
]

# Har bir holat tugaganda umumiy progress (%)
PROJECT_PROGRESS = {
    ProjectStatus.UPLOADED: 0,
    ProjectStatus.STEM_SEPARATION: 15,
    ProjectStatus.TRANSCRIBED: 35,
    ProjectStatus.TRANSLATED: 50,
    ProjectStatus.TTS_DISPATCHED: 75,
    ProjectStatus.TIMING_ALIGNED: 85,
    ProjectStatus.MASTERED: 95,
    ProjectStatus.READY_FOR_EXPORT: 100,
}
BOOK_PROGRESS = {
    BookStatus.UPLOADED: 0,
    BookStatus.PARSED: 5,
    BookStatus.NORMALIZED: 10,
    BookStatus.SEGMENTED: 15,
    BookStatus.ATTRIBUTED: 30,
    BookStatus.LEXICON_APPLIED: 35,
    BookStatus.TTS_DISPATCHED: 85,
    BookStatus.STITCHED: 95,
    BookStatus.READY_FOR_EXPORT: 100,
}


class InvalidTransition(Exception):
    pass


def _check(flow, current, target, failed):
    if target == failed:
        return True
    if current == failed:
        # Qayta ishga tushirish: FAILED dan istalgan bosqichga qaytish mumkin
        return True
    ci, ti = flow.index(current), flow.index(target)
    # Oldinga bir qadam yoki qoʻlda tahrirdan keyin orqaga (qayta ishlash)
    return ti == ci + 1 or ti <= ci


def can_transition_project(current: ProjectStatus, target: ProjectStatus) -> bool:
    return _check(PROJECT_FLOW, current, target, ProjectStatus.FAILED)


def can_transition_book(current: BookStatus, target: BookStatus) -> bool:
    return _check(BOOK_FLOW, current, target, BookStatus.FAILED)


def assert_project_transition(current: ProjectStatus, target: ProjectStatus) -> None:
    if not can_transition_project(current, target):
        raise InvalidTransition(f"{current.value} → {target.value} oʻtish mumkin emas")


def assert_book_transition(current: BookStatus, target: BookStatus) -> None:
    if not can_transition_book(current, target):
        raise InvalidTransition(f"{current.value} → {target.value} oʻtish mumkin emas")
