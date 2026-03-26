from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.models import LlmOperation, SyncJob, Thread, User
from app.db.session import async_session_maker
from app.gmail.dto import ThreadPayload
from app.llm.classifier import classify_threads_batch
from app.services import jobs as job_service
from app.services.thread_ops import apply_classifications

logger = logging.getLogger(__name__)

SENTINEL = object()


@dataclass(frozen=True)
class RecategorizeBatch:
    payloads: list[ThreadPayload]
    gmail_to_thread_id: dict[str, uuid.UUID]


async def run_recategorize_job(job_id: uuid.UUID) -> None:
    settings = get_settings()
    try:
        user_id, allowed_labels = await _recat_bootstrap(job_id)
        await _recat_pipeline(
            job_id=job_id,
            user_id=user_id,
            allowed_labels=allowed_labels,
            settings=settings,
        )
        async with async_session_maker() as session:
            async with session.begin():
                await job_service.mark_job_completed(session, job_id)
    except Exception as e:
        logger.exception("Recategorize job failed")
        async with async_session_maker() as session:
            async with session.begin():
                await job_service.mark_job_failed(session, job_id, str(e))


async def _recat_bootstrap(job_id: uuid.UUID) -> tuple[uuid.UUID, list[str]]:
    async with async_session_maker() as session:
        async with session.begin():
            job = await session.get(SyncJob, job_id)
            if job is None:
                raise RuntimeError("Job not found")
            user = await session.get(User, job.user_id)
            if user is None:
                raise RuntimeError("User not found")
            await job_service.mark_job_running(session, job_id)
            labels = job.allowed_labels_snapshot
            if not labels:
                raise RuntimeError("Missing allowed_labels_snapshot")
            return user.id, list(labels)


async def _recat_pipeline(
    *,
    job_id: uuid.UUID,
    user_id: uuid.UUID,
    allowed_labels: list[str],
    settings: Settings,
) -> None:
    queue: asyncio.Queue[RecategorizeBatch | object] = asyncio.Queue(maxsize=settings.queue_maxsize)
    llm_sem = asyncio.Semaphore(settings.max_parallel_llm_batches)
    num_consumers = max(1, settings.max_parallel_llm_batches)

    async def producer() -> None:
        cursor_date: int | None = None
        cursor_id: uuid.UUID | None = None
        async with async_session_maker() as session:
            while True:
                stmt = (
                    select(Thread)
                    .where(Thread.user_id == user_id)
                    .order_by(Thread.internal_date.desc(), Thread.id.desc())
                    .limit(settings.gmail_batch_size)
                )
                if cursor_date is not None and cursor_id is not None:
                    stmt = stmt.where(
                        (Thread.internal_date < cursor_date)
                        | ((Thread.internal_date == cursor_date) & (Thread.id < cursor_id))
                    )
                result = await session.execute(stmt)
                rows = list(result.scalars().all())
                if not rows:
                    break
                payloads = [
                    ThreadPayload(
                        gmail_thread_id=t.gmail_thread_id,
                        subject=t.subject,
                        snippet=t.snippet,
                        internal_date=t.internal_date,
                        from_addr=t.from_addr,
                    )
                    for t in rows
                ]
                gmap = {t.gmail_thread_id: t.id for t in rows}
                await queue.put(RecategorizeBatch(payloads=payloads, gmail_to_thread_id=gmap))
                last = rows[-1]
                cursor_date = last.internal_date
                cursor_id = last.id
        for _ in range(num_consumers):
            await queue.put(SENTINEL)

    async def consumer() -> None:
        while True:
            batch = await queue.get()
            try:
                if batch is SENTINEL:
                    return
                assert isinstance(batch, RecategorizeBatch)
                async with llm_sem:
                    async with async_session_maker() as w_session:
                        async with w_session.begin():
                            classifications = await classify_threads_batch(
                                session=w_session,
                                settings=settings,
                                user_id=user_id,
                                job_id=job_id,
                                operation=LlmOperation.after_new_categories,
                                allowed_labels=allowed_labels,
                                threads=batch.payloads,
                            )
                            await apply_classifications(
                                w_session,
                                user_id,
                                classifications,
                                batch.gmail_to_thread_id,
                            )
                    async with async_session_maker() as j_session:
                        async with j_session.begin():
                            await job_service.increment_job_batches(j_session, job_id)
            finally:
                queue.task_done()

    await asyncio.gather(producer(), *[consumer() for _ in range(num_consumers)])
