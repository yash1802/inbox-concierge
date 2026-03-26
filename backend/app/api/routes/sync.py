from __future__ import annotations

import asyncio
import logging
import uuid

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.auth.deps import CurrentUser, SessionDep
from app.db.models import JobKind
from app.services import jobs as job_service
from app.services.sync_service import run_sync_job

router = APIRouter(prefix="/sync", tags=["sync"])
logger = logging.getLogger(__name__)


class StartSyncOut(BaseModel):
    job_id: str


@router.post("", response_model=StartSyncOut, status_code=status.HTTP_202_ACCEPTED)
async def start_sync(user: CurrentUser, session: SessionDep) -> StartSyncOut:
    if await job_service.has_active_job(session, user.id):
        raise HTTPException(status_code=409, detail="A sync or recategorize job is already running")
    job = await job_service.create_job(session, user.id, JobKind.sync.value)
    await session.commit()
    jid = job.id

    task = asyncio.create_task(run_sync_job(jid))

    def _done(t: asyncio.Task[None]) -> None:
        try:
            t.result()
        except Exception:
            logger.exception("Background sync job raised")

    task.add_done_callback(_done)
    return StartSyncOut(job_id=str(jid))
