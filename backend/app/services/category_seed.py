import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Category
from app.utils.category_norm import normalize_category_name

DEFAULT_CATEGORY_NAMES = ("Important", "Can wait", "Newsletter", "Transactional", "FYI")

# System default used when the model returns no valid labels (must exist after seeding).
CLASSIFICATION_FALLBACK_CATEGORY_NAME = "FYI"


async def ensure_default_categories(session: AsyncSession, user_id: uuid.UUID) -> None:
    result = await session.execute(select(Category.id).where(Category.user_id == user_id).limit(1))
    if result.scalar_one_or_none() is not None:
        return
    for name in DEFAULT_CATEGORY_NAMES:
        norm = normalize_category_name(name)
        session.add(
            Category(
                user_id=user_id,
                name=name,
                normalized_name=norm,
                is_system=True,
            )
        )
    await session.flush()


async def list_allowed_labels(session: AsyncSession, user_id: uuid.UUID) -> list[str]:
    result = await session.execute(
        select(Category.name).where(Category.user_id == user_id).order_by(Category.name.asc())
    )
    return list(result.scalars().all())
