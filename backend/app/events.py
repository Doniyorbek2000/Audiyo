"""Real vaqt hodisalari: ishchilar Redis Pub/Sub ga yozadi, API SSE orqali uzatadi.

Hodisa sxemasi (JSON):
{
  "type": "status" | "progress" | "segment" | "block" | "cost" | "error",
  "entity": "project" | "book",
  "id": "<uuid>",
  "status": "<ProjectStatus|BookStatus>",
  "stage": "<bosqich nomi>",
  "progress": 0..100,
  "message": "<inson oʻqiydigan matn>",
  "data": {...},
  "ts": "<ISO-8601>"
}
"""
import json
from datetime import UTC, datetime
from typing import Any

import redis
import redis.asyncio as aioredis

from app.config import get_settings

_sync_client: redis.Redis | None = None


def channel(entity: str, entity_id: str) -> str:
    return f"audiyo:events:{entity}:{entity_id}"


def build_event(
    entity: str,
    entity_id: str,
    type_: str,
    *,
    status: str | None = None,
    stage: str | None = None,
    progress: float | None = None,
    message: str | None = None,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "type": type_,
        "entity": entity,
        "id": str(entity_id),
        "status": status,
        "stage": stage,
        "progress": None if progress is None else round(float(progress), 2),
        "message": message,
        "data": data or {},
        "ts": datetime.now(UTC).isoformat(),
    }


def publish(entity: str, entity_id: str, type_: str, **kwargs: Any) -> None:
    global _sync_client
    if _sync_client is None:
        _sync_client = redis.Redis.from_url(get_settings().redis_url)
    event = build_event(entity, str(entity_id), type_, **kwargs)
    try:
        _sync_client.publish(channel(entity, str(entity_id)), json.dumps(event, ensure_ascii=False))
    except redis.RedisError:
        pass  # hodisa yoʻqolishi konveyerni toʻxtatmasligi kerak


async def subscribe(entity: str, entity_id: str):
    client = aioredis.Redis.from_url(get_settings().redis_url)
    pubsub = client.pubsub()
    await pubsub.subscribe(channel(entity, entity_id))
    try:
        while True:
            msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=15.0)
            yield None if msg is None else msg["data"].decode()
    finally:
        await pubsub.unsubscribe()
        await pubsub.aclose()
        await client.aclose()
