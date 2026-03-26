import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from app.auth.deps import CurrentUser, SessionDep
from app.db.models import SyncJob

router = APIRouter(prefix="/jobs", tags=["jobs"])


class JobStatusOut(BaseModel):
    id: str
    kind: str
    status: str
    error_message: str | None
    batches_done: int
    batches_total: int | None
    allowed_labels_snapshot: list[str] | None
    started_at: datetime | None
    finished_at: datetime | None


@router.get("/{job_id}", response_model=JobStatusOut)
async def get_job(job_id: str, user: CurrentUser, session: SessionDep) -> JobStatusOut:
    try:
        jid = uuid.UUID(job_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="Invalid job id") from e
    result = await session.execute(select(SyncJob).where(SyncJob.id == jid, SyncJob.user_id == user.id))
    job = result.scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobStatusOut(
        id=str(job.id),
        kind=job.kind,
        status=job.status,
        error_message=job.error_message,
        batches_done=job.batches_done,
        batches_total=job.batches_total,
        allowed_labels_snapshot=list(job.allowed_labels_snapshot)
        if job.allowed_labels_snapshot
        else None,
        started_at=job.started_at,
        finished_at=job.finished_at,
    )
