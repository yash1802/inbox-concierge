from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime

import httpx
from cryptography.fernet import Fernet
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.crypto import decrypt_secret
from app.config import Settings, get_settings
from app.db.models import LlmOperation, SyncJob, Thread, User, UserSyncState
from app.db.session import async_session_maker
from app.gmail.client import GmailClient, GmailHttpError, fetch_threads_page_details
from app.gmail.dto import ThreadPayload
from app.gmail.google_credentials import build_credentials_from_refresh, ensure_fresh_access_token
from app.llm.classifier import classify_threads_batch
from app.services import jobs as job_service
from app.services.category_seed import list_allowed_labels
from app.services.thread_ops import apply_classifications, upsert_threads

logger = logging.getLogger(__name__)

SENTINEL = object()


def _gmail_query_after_ms(ms: int | None) -> str | None:
    if ms is None:
        return None
    dt = datetime.fromtimestamp(ms / 1000.0, tz=UTC)
    return f"after:{dt.year}/{dt.month:02d}/{dt.day:02d}"


async def run_sync_job(job_id: uuid.UUID) -> None:
    settings = get_settings()
    try:
        user_id, access_token, q, allowed_labels = await _sync_bootstrap(job_id, settings)
        await _sync_pipeline(
            job_id=job_id,
            user_id=user_id,
            access_token=access_token,
            q=q,
            allowed_labels=allowed_labels,
            settings=settings,
        )
        await _sync_finalize(job_id, user_id)
    except Exception as e:
        logger.exception("Sync job failed")
        async with async_session_maker() as session:
            async with session.begin():
                await job_service.mark_job_failed(session, job_id, str(e))


async def _sync_bootstrap(
    job_id: uuid.UUID, settings: Settings
) -> tuple[uuid.UUID, str, str | None, list[str]]:
    async with async_session_maker() as session:
        async with session.begin():
            job = await session.get(SyncJob, job_id)
            if job is None:
                raise RuntimeError("Job not found")
            user = await session.get(User, job.user_id)
            if user is None or not user.encrypted_refresh_token:
                raise RuntimeError("Missing user or refresh token")
            await job_service.mark_job_running(session, job_id)

            fernet = Fernet(settings.token_encryption_key.encode("utf-8"))
            refresh = decrypt_secret(fernet, user.encrypted_refresh_token)
            scopes = (user.token_scopes or "").split()
            if not scopes:
                scopes = [
                    "openid",
                    "https://www.googleapis.com/auth/userinfo.email",
                    "https://www.googleapis.com/auth/gmail.readonly",
                ]

            creds = build_credentials_from_refresh(settings, refresh, scopes)
            access_token = await ensure_fresh_access_token(creds)

            sync_row = await session.get(UserSyncState, user.id)
            newest_ms = sync_row.newest_thread_internal_date_ms if sync_row else None
            q = _gmail_query_after_ms(newest_ms)
            allowed_labels = await list_allowed_labels(session, user.id)

            return user.id, access_token, q, allowed_labels


async def _sync_pipeline(
    *,
    job_id: uuid.UUID,
    user_id: uuid.UUID,
    access_token: str,
    q: str | None,
    allowed_labels: list[str],
    settings: Settings,
) -> None:
    queue: asyncio.Queue[list[ThreadPayload] | object] = asyncio.Queue(maxsize=settings.queue_maxsize)
    gmail_sem = asyncio.Semaphore(settings.max_parallel_gmail_batches)
    llm_sem = asyncio.Semaphore(settings.max_parallel_llm_batches)
    num_consumers = max(1, settings.max_parallel_llm_batches)

    async def producer() -> None:
        collected = 0
        page_token: str | None = None
        async with httpx.AsyncClient() as http:
            client = GmailClient(http)
            while collected < settings.sync_max_threads:
                async with gmail_sem:
                    try:
                        ids, next_tok = await client.list_thread_ids(
                            access_token,
                            max_results=settings.gmail_batch_size,
                            page_token=page_token,
                            q=q,
                        )
                    except GmailHttpError as e:
                        raise RuntimeError(f"Gmail list failed: {e}") from e
                if not ids:
                    break
                async with gmail_sem:
                    details = await fetch_threads_page_details(
                        client,
                        access_token,
                        ids,
                        max_parallel=settings.gmail_batch_size,
                    )
                await queue.put(details)
                collected += len(details)
                if not next_tok:
                    break
                page_token = next_tok
        for _ in range(num_consumers):
            await queue.put(SENTINEL)

    async def consumer() -> None:
        while True:
            batch = await queue.get()
            try:
                if batch is SENTINEL:
                    return
                assert isinstance(batch, list)
                async with llm_sem:
                    async with async_session_maker() as w_session:
                        async with w_session.begin():
                            gmail_map = await upsert_threads(w_session, user_id, batch)
                            classifications = await classify_threads_batch(
                                session=w_session,
                                settings=settings,
                                user_id=user_id,
                                job_id=job_id,
                                operation=LlmOperation.initial_classify,
                                allowed_labels=allowed_labels,
                                threads=batch,
                            )
                            await apply_classifications(
                                w_session, user_id, classifications, gmail_map
                            )
                    async with async_session_maker() as j_session:
                        async with j_session.begin():
                            await job_service.increment_job_batches(j_session, job_id)
            finally:
                queue.task_done()

    await asyncio.gather(producer(), *[consumer() for _ in range(num_consumers)])


async def _sync_finalize(job_id: uuid.UUID, user_id: uuid.UUID) -> None:
    async with async_session_maker() as session:
        async with session.begin():
            subq = select(func.max(Thread.internal_date)).where(Thread.user_id == user_id)
            res = await session.execute(subq)
            max_ms = res.scalar_one_or_none()
            sync_row = await session.get(UserSyncState, user_id)
            if sync_row is None:
                session.add(
                    UserSyncState(user_id=user_id, newest_thread_internal_date_ms=max_ms)
                )
            elif max_ms is not None:
                prev = sync_row.newest_thread_internal_date_ms
                sync_row.newest_thread_internal_date_ms = max(prev or 0, max_ms)
            await job_service.mark_job_completed(session, job_id)
