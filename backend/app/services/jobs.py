from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import JobStatus, SyncJob


async def has_active_job(session: AsyncSession, user_id: uuid.UUID) -> bool:
    result = await session.execute(
        select(SyncJob.id).where(
            SyncJob.user_id == user_id,
            SyncJob.status.in_([JobStatus.pending.value, JobStatus.running.value]),
        )
    )
    return result.scalar_one_or_none() is not None


async def create_job(
    session: AsyncSession,
    user_id: uuid.UUID,
    kind: str,
    allowed_labels_snapshot: list[str] | None = None,
) -> SyncJob:
    job = SyncJob(
        user_id=user_id,
        kind=kind,
        status=JobStatus.pending.value,
        allowed_labels_snapshot=allowed_labels_snapshot,
        batches_done=0,
    )
    session.add(job)
    await session.flush()
    return job


async def mark_job_running(session: AsyncSession, job_id: uuid.UUID) -> None:
    await session.execute(
        update(SyncJob)
        .where(SyncJob.id == job_id)
        .values(status=JobStatus.running.value, started_at=datetime.now(tz=UTC))
    )
    await session.flush()


async def mark_job_completed(session: AsyncSession, job_id: uuid.UUID) -> None:
    await session.execute(
        update(SyncJob)
        .where(SyncJob.id == job_id)
        .values(status=JobStatus.completed.value, finished_at=datetime.now(tz=UTC))
    )
    await session.flush()


async def mark_job_failed(session: AsyncSession, job_id: uuid.UUID, message: str) -> None:
    await session.execute(
        update(SyncJob)
        .where(SyncJob.id == job_id)
        .values(
            status=JobStatus.failed.value,
            finished_at=datetime.now(tz=UTC),
            error_message=message[:4000],
        )
    )
    await session.flush()


async def increment_job_batches(session: AsyncSession, job_id: uuid.UUID) -> None:
    await session.execute(
        update(SyncJob)
        .where(SyncJob.id == job_id)
        .values(batches_done=SyncJob.batches_done + 1)
    )
    await session.flush()
