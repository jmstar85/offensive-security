"""Request-scoped ContextVar for per-user credential propagation (PR1.4).

CURRENT_USER_ID is set at the request entrypoint (FastAPI Depends) and
inherited by every asyncio Task spawned via copy_context() so that
credential_resolver can identify the calling user without thread-local
state or explicit parameter threading.
"""
from __future__ import annotations

import contextlib
import uuid
from contextvars import ContextVar, Token
from typing import Generator

CURRENT_USER_ID: ContextVar[uuid.UUID | None] = ContextVar("CURRENT_USER_ID", default=None)


def get_current_user_id() -> uuid.UUID | None:
    return CURRENT_USER_ID.get()


@contextlib.contextmanager
def with_user_context(user_id: uuid.UUID) -> Generator[None, None, None]:
    """Set CURRENT_USER_ID for the duration of the with-block, then restore."""
    token: Token[uuid.UUID | None] = CURRENT_USER_ID.set(user_id)
    try:
        yield
    finally:
        CURRENT_USER_ID.reset(token)
