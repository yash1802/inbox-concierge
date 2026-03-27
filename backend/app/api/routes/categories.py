from __future__ import annotations

import asyncio
import logging
import uuid

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import delete, select

from app.auth.deps import CurrentUser, SessionDep
from app.rate_limit import limiter, rate_limit_key_user_or_ip
from app.db.models import Category, JobKind, ThreadCategory
from app.services import jobs as job_service
from app.services.category_seed import list_allowed_labels
from app.utils.category_norm import normalize_category_name
from app.services.recategorize_service import run_recategorize_job

router = APIRouter(prefix="/categories", tags=["categories"])
logger = logging.getLogger(__name__)


class CategoryOut(BaseModel):
    id: str
    name: str
    is_system: bool


class AddCategoriesBody(BaseModel):
    names: str


class AddCategoriesOut(BaseModel):
    job_id: str
    added: list[str]


class RecategorizeAllOut(BaseModel):
    job_id: str


@router.get("", response_model=list[CategoryOut])
async def list_categories(
    user: CurrentUser, session: SessionDep, response: Response
) -> list[CategoryOut]:
    result = await session.execute(
        select(Category).where(Category.user_id == user.id).order_by(Category.name.asc())
    )
    rows = result.scalars().all()
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    return [CategoryOut(id=str(c.id), name=c.name, is_system=c.is_system) for c in rows]


@router.post("", response_model=AddCategoriesOut, status_code=status.HTTP_202_ACCEPTED)
@limiter.limit(
    "5/3hours",
    key_func=rate_limit_key_user_or_ip,
    error_message="You can add new categories at most 5 times every 3 hours. Try again later.",
)
async def add_categories(
    request: Request, body: AddCategoriesBody, user: CurrentUser, session: SessionDep
) -> AddCategoriesOut:
    if await job_service.has_active_job(session, user.id):
        raise HTTPException(status_code=409, detail="A sync or recategorize job is already running")
    raw_parts = [p.strip() for p in body.names.split(",")]
    names = [p for p in raw_parts if p]
    if not names:
        raise HTTPException(status_code=400, detail="No category names provided")
    added: list[str] = []
    for name in names:
        norm = normalize_category_name(name)
        existing = await session.execute(
            select(Category.id).where(
                Category.user_id == user.id, Category.normalized_name == norm
            )
        )
        if existing.scalar_one_or_none() is not None:
            continue
        session.add(
            Category(
                user_id=user.id,
                name=name,
                normalized_name=norm,
                is_system=False,
            )
        )
        added.append(name)
    if not added:
        raise HTTPException(status_code=400, detail="All category names already exist")
    await session.flush()
    labels = await list_allowed_labels(session, user.id)
    job = await job_service.create_job(
        session,
        user.id,
        JobKind.recategorize.value,
        allowed_labels_snapshot=labels,
    )
    await session.commit()
    job_id = job.id

    task = asyncio.create_task(run_recategorize_job(job_id))

    def _done(t: asyncio.Task[None]) -> None:
        try:
            t.result()
        except Exception:
            logger.exception("Background recategorize job raised")

    task.add_done_callback(_done)
    return AddCategoriesOut(job_id=str(job_id), added=added)


@router.post(
    "/recategorize-all",
    response_model=RecategorizeAllOut,
    status_code=status.HTTP_202_ACCEPTED,
)
@limiter.limit(
    "5/3hours",
    key_func=rate_limit_key_user_or_ip,
    error_message="You can re-categorize all threads at most 5 times every 3 hours. Try again later.",
)
async def recategorize_all(request: Request, user: CurrentUser, session: SessionDep) -> RecategorizeAllOut:
    if await job_service.has_active_job(session, user.id):
        raise HTTPException(
            status_code=409,
            detail="A sync or recategorize job is already running",
        )
    labels = await list_allowed_labels(session, user.id)
    job = await job_service.create_job(
        session,
        user.id,
        JobKind.recategorize.value,
        allowed_labels_snapshot=labels,
    )
    await session.commit()
    job_id = job.id

    task = asyncio.create_task(run_recategorize_job(job_id))

    def _done(t: asyncio.Task[None]) -> None:
        try:
            t.result()
        except Exception:
            logger.exception("Background recategorize job raised")

    task.add_done_callback(_done)
    return RecategorizeAllOut(job_id=str(job_id))


@router.delete("/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_category(category_id: str, user: CurrentUser, session: SessionDep) -> None:
    if await job_service.has_active_job(session, user.id):
        raise HTTPException(
            status_code=409,
            detail="Wait for the current sync or recategorization to finish before deleting categories.",
        )
    try:
        cid = uuid.UUID(category_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="Invalid category id") from e
    chk = await session.execute(
        select(Category.id, Category.is_system).where(Category.id == cid, Category.user_id == user.id)
    )
    row = chk.first()
    if row is None:
        raise HTTPException(status_code=404, detail="Category not found")
    _, is_system = row
    if is_system:
        raise HTTPException(status_code=400, detail="Cannot delete system categories")
    # Join rows first; categories.id is referenced by thread_categories (CASCADE also applies at DB).
    await session.execute(delete(ThreadCategory).where(ThreadCategory.category_id == cid))
    del_cat = await session.execute(delete(Category).where(Category.id == cid, Category.user_id == user.id))
    if del_cat.rowcount != 1:
        await session.rollback()
        raise HTTPException(status_code=404, detail="Category not found")
    await session.commit()
