from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.db.models import SyncJob, User
from app.services import recategorize_service
from tests.unit.conftest import fake_db_session


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_recategorize_job_success(mocker: pytest.MockFixture) -> None:
    jid = uuid.uuid4()
    uid = uuid.uuid4()
    mocker.patch(
        "app.services.recategorize_service._recat_bootstrap",
        new=AsyncMock(return_value=(uid, ["Important", "FYI"])),
    )
    mocker.patch("app.services.recategorize_service._recat_pipeline", new=AsyncMock())

    session = fake_db_session()
    mocker.patch(
        "app.services.recategorize_service.async_session_maker",
        return_value=MagicMock(
            __aenter__=AsyncMock(return_value=session),
            __aexit__=AsyncMock(return_value=None),
        ),
    )
    completed = mocker.patch(
        "app.services.recategorize_service.job_service.mark_job_completed",
        new=AsyncMock(),
    )
    failed = mocker.patch(
        "app.services.recategorize_service.job_service.mark_job_failed",
        new=AsyncMock(),
    )

    await recategorize_service.run_recategorize_job(jid)

    completed.assert_awaited_once_with(session, jid)
    failed.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_recategorize_job_marks_failed_when_pipeline_raises(mocker: pytest.MockFixture) -> None:
    jid = uuid.uuid4()
    uid = uuid.uuid4()
    mocker.patch(
        "app.services.recategorize_service._recat_bootstrap",
        new=AsyncMock(return_value=(uid, ["A"])),
    )
    mocker.patch(
        "app.services.recategorize_service._recat_pipeline",
        new=AsyncMock(side_effect=RuntimeError("LLM down")),
    )

    fail_session = fake_db_session()
    mocker.patch(
        "app.services.recategorize_service.async_session_maker",
        return_value=MagicMock(
            __aenter__=AsyncMock(return_value=fail_session),
            __aexit__=AsyncMock(return_value=None),
        ),
    )
    completed = mocker.patch(
        "app.services.recategorize_service.job_service.mark_job_completed",
        new=AsyncMock(),
    )
    failed = mocker.patch(
        "app.services.recategorize_service.job_service.mark_job_failed",
        new=AsyncMock(),
    )

    await recategorize_service.run_recategorize_job(jid)

    completed.assert_not_called()
    failed.assert_awaited_once_with(fail_session, jid, "LLM down")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_recat_bootstrap_success(mocker: pytest.MockFixture) -> None:
    jid = uuid.uuid4()
    uid = uuid.uuid4()

    job = MagicMock(spec=SyncJob)
    job.user_id = uid
    job.allowed_labels_snapshot = ["Newsletter", "FYI"]

    user = MagicMock(spec=User)
    user.id = uid

    session = fake_db_session()
    session.get = AsyncMock(side_effect=[job, user])

    mocker.patch(
        "app.services.recategorize_service.async_session_maker",
        return_value=MagicMock(
            __aenter__=AsyncMock(return_value=session),
            __aexit__=AsyncMock(return_value=None),
        ),
    )
    mocker.patch(
        "app.services.recategorize_service.job_service.mark_job_running",
        new=AsyncMock(),
    )

    out_uid, labels = await recategorize_service._recat_bootstrap(jid)

    assert out_uid == uid
    assert labels == ["Newsletter", "FYI"]
    recategorize_service.job_service.mark_job_running.assert_awaited_once_with(session, jid)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_recat_bootstrap_missing_snapshot_raises(mocker: pytest.MockFixture) -> None:
    jid = uuid.uuid4()
    uid = uuid.uuid4()

    job = MagicMock(spec=SyncJob)
    job.user_id = uid
    job.allowed_labels_snapshot = None

    user = MagicMock(spec=User)
    user.id = uid

    session = fake_db_session()
    session.get = AsyncMock(side_effect=[job, user])

    mocker.patch(
        "app.services.recategorize_service.async_session_maker",
        return_value=MagicMock(
            __aenter__=AsyncMock(return_value=session),
            __aexit__=AsyncMock(return_value=None),
        ),
    )
    mocker.patch(
        "app.services.recategorize_service.job_service.mark_job_running",
        new=AsyncMock(),
    )

    with pytest.raises(RuntimeError, match="Missing allowed_labels_snapshot"):
        await recategorize_service._recat_bootstrap(jid)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_recat_pipeline_no_threads(mocker: pytest.MockFixture) -> None:
    jid = uuid.uuid4()
    uid = uuid.uuid4()
    settings = MagicMock()
    settings.queue_maxsize = 10
    settings.gmail_batch_size = 20
    settings.max_parallel_llm_batches = 2

    empty_result = MagicMock()
    empty_result.scalars.return_value.all.return_value = []

    producer_session = AsyncMock()
    producer_session.execute = AsyncMock(return_value=empty_result)

    mocker.patch(
        "app.services.recategorize_service.async_session_maker",
        return_value=MagicMock(
            __aenter__=AsyncMock(return_value=producer_session),
            __aexit__=AsyncMock(return_value=None),
        ),
    )
    classify = mocker.patch(
        "app.services.recategorize_service.classify_threads_batch",
        new=AsyncMock(),
    )

    await recategorize_service._recat_pipeline(
        job_id=jid,
        user_id=uid,
        allowed_labels=["A"],
        settings=settings,
    )

    classify.assert_not_called()
