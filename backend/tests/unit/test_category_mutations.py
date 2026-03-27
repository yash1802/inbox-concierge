from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.db.models import Category, JobKind
from tests.unit.conftest import fake_db_session
from app.services import category_mutations
from app.services.category_mutations import (
    AllCategoryNamesExistError,
    create_recategorize_job_after_category_change,
    insert_new_categories,
)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_insert_new_categories_adds_when_none_exist() -> None:
    uid = uuid.uuid4()
    session = fake_db_session()
    exec_result = MagicMock()
    exec_result.scalar_one_or_none.return_value = None
    session.execute = AsyncMock(return_value=exec_result)

    added = await insert_new_categories(session, uid, ["Jobs", "Receipts"])

    assert added == ["Jobs", "Receipts"]
    assert session.add.call_count == 2
    added_rows = [c.args[0] for c in session.add.call_args_list]
    assert all(isinstance(r, Category) for r in added_rows)
    assert {r.name for r in added_rows} == {"Jobs", "Receipts"}
    assert all(r.user_id == uid and not r.is_system for r in added_rows)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_insert_new_categories_skips_existing() -> None:
    uid = uuid.uuid4()
    session = fake_db_session()
    # First name exists, second is new
    results = [MagicMock(scalar_one_or_none=MagicMock(return_value=uuid.uuid4())), MagicMock(scalar_one_or_none=MagicMock(return_value=None))]
    session.execute = AsyncMock(side_effect=results)

    added = await insert_new_categories(session, uid, ["Old", "New"])

    assert added == ["New"]
    session.add.assert_called_once()
    assert session.add.call_args[0][0].name == "New"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_insert_new_categories_empty_names_raises() -> None:
    session = fake_db_session()
    with pytest.raises(ValueError, match="No category names"):
        await insert_new_categories(session, uuid.uuid4(), [])


@pytest.mark.unit
@pytest.mark.asyncio
async def test_insert_new_categories_all_exist_raises() -> None:
    uid = uuid.uuid4()
    session = fake_db_session()
    exec_result = MagicMock()
    exec_result.scalar_one_or_none.return_value = uuid.uuid4()
    session.execute = AsyncMock(return_value=exec_result)

    with pytest.raises(AllCategoryNamesExistError):
        await insert_new_categories(session, uid, ["Dup"])


@pytest.mark.unit
@pytest.mark.asyncio
async def test_create_recategorize_job_after_category_change(mocker: pytest.MockFixture) -> None:
    uid = uuid.uuid4()
    session = fake_db_session()
    job_id = uuid.uuid4()
    fake_job = MagicMock(id=job_id)

    mocker.patch(
        "app.services.category_mutations.list_allowed_labels",
        new=AsyncMock(return_value=["A", "B"]),
    )
    mocker.patch(
        "app.services.category_mutations.job_service.create_job",
        new=AsyncMock(return_value=fake_job),
    )

    out = await create_recategorize_job_after_category_change(session, uid)

    assert out == job_id
    session.flush.assert_awaited_once()
    category_mutations.job_service.create_job.assert_awaited_once()
    call_kw = category_mutations.job_service.create_job.await_args
    assert call_kw[0][1] == uid
    assert call_kw[0][2] == JobKind.recategorize.value
    assert call_kw[1]["allowed_labels_snapshot"] == ["A", "B"]
