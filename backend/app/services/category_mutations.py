from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Category, JobKind
from app.services import jobs as job_service
from app.services.category_seed import list_allowed_labels
from app.utils.category_norm import normalize_category_name


class AllCategoryNamesExistError(ValueError):
    """Every requested name already exists for the user."""


async def insert_new_categories(
    session: AsyncSession,
    user_id: uuid.UUID,
    names: list[str],
) -> list[str]:
    """
    Insert non-system categories for names not already present (normalized).
    `names` must be a non-empty list of trimmed display strings.
    """
    if not names:
        raise ValueError("No category names provided")
    added: list[str] = []
    for name in names:
        norm = normalize_category_name(name)
        existing = await session.execute(
            select(Category.id).where(
                Category.user_id == user_id, Category.normalized_name == norm
            )
        )
        if existing.scalar_one_or_none() is not None:
            continue
        session.add(
            Category(
                user_id=user_id,
                name=name,
                normalized_name=norm,
                is_system=False,
            )
        )
        added.append(name)
    if not added:
        raise AllCategoryNamesExistError("All category names already exist")
    return added


async def create_recategorize_job_after_category_change(
    session: AsyncSession,
    user_id: uuid.UUID,
) -> uuid.UUID:
    await session.flush()
    labels = await list_allowed_labels(session, user_id)
    job = await job_service.create_job(
        session,
        user_id,
        JobKind.recategorize.value,
        allowed_labels_snapshot=labels,
    )
    return job.id
