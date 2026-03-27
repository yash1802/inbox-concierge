from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.gmail.client import GmailHttpError
from app.services import sync_service
from tests.unit.conftest import fake_db_session


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_sync_job_success(mocker: pytest.MockFixture) -> None:
    jid = uuid.uuid4()
    uid = uuid.uuid4()
    mocker.patch(
        "app.services.sync_service._sync_bootstrap",
        new=AsyncMock(return_value=(uid, "access-token", None, ["Important"])),
    )
    pipeline = mocker.patch("app.services.sync_service._sync_pipeline", new=AsyncMock())
    finalize = mocker.patch("app.services.sync_service._sync_finalize", new=AsyncMock())
    failed = mocker.patch("app.services.sync_service.job_service.mark_job_failed", new=AsyncMock())

    await sync_service.run_sync_job(jid)

    pipeline.assert_awaited_once()
    finalize.assert_awaited_once_with(jid, uid)
    failed.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_sync_job_marks_failed_when_bootstrap_raises(mocker: pytest.MockFixture) -> None:
    jid = uuid.uuid4()
    mocker.patch(
        "app.services.sync_service._sync_bootstrap",
        new=AsyncMock(side_effect=RuntimeError("Missing user or refresh token")),
    )
    session = fake_db_session()
    mocker.patch(
        "app.services.sync_service.async_session_maker",
        return_value=MagicMock(
            __aenter__=AsyncMock(return_value=session),
            __aexit__=AsyncMock(return_value=None),
        ),
    )
    failed = mocker.patch("app.services.sync_service.job_service.mark_job_failed", new=AsyncMock())

    await sync_service.run_sync_job(jid)

    failed.assert_awaited_once()
    assert failed.await_args[0][1] == jid
    assert "Missing user" in failed.await_args[0][2]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_sync_pipeline_no_threads_no_gmail_details_call(mocker: pytest.MockFixture) -> None:
    jid = uuid.uuid4()
    uid = uuid.uuid4()
    settings = MagicMock()
    settings.queue_maxsize = 10
    settings.sync_max_threads = 100
    settings.gmail_batch_size = 20
    settings.max_parallel_gmail_batches = 2
    settings.max_parallel_llm_batches = 2

    http_cm = MagicMock()
    http_cm.__aenter__ = AsyncMock(return_value=http_cm)
    http_cm.__aexit__ = AsyncMock(return_value=None)
    mocker.patch("app.services.sync_service.httpx.AsyncClient", return_value=http_cm)

    gmail_cls = mocker.patch("app.services.sync_service.GmailClient")
    gmail_inst = gmail_cls.return_value
    gmail_inst.list_thread_ids = AsyncMock(return_value=([], None))

    fetch_details = mocker.patch(
        "app.services.sync_service.fetch_threads_page_details",
        new=AsyncMock(),
    )

    await sync_service._sync_pipeline(
        job_id=jid,
        user_id=uid,
        access_token="tok",
        q=None,
        allowed_labels=["X"],
        settings=settings,
    )

    fetch_details.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_sync_pipeline_gmail_list_error_propagates(mocker: pytest.MockFixture) -> None:
    jid = uuid.uuid4()
    uid = uuid.uuid4()
    settings = MagicMock()
    settings.queue_maxsize = 10
    settings.sync_max_threads = 100
    settings.gmail_batch_size = 20
    settings.max_parallel_gmail_batches = 2
    settings.max_parallel_llm_batches = 2

    http_cm = MagicMock()
    http_cm.__aenter__ = AsyncMock(return_value=http_cm)
    http_cm.__aexit__ = AsyncMock(return_value=None)
    mocker.patch("app.services.sync_service.httpx.AsyncClient", return_value=http_cm)

    gmail_cls = mocker.patch("app.services.sync_service.GmailClient")
    gmail_inst = gmail_cls.return_value
    gmail_inst.list_thread_ids = AsyncMock(side_effect=GmailHttpError(429, "quota"))

    with pytest.raises(RuntimeError, match="Gmail list failed"):
        await sync_service._sync_pipeline(
            job_id=jid,
            user_id=uid,
            access_token="tok",
            q=None,
            allowed_labels=["X"],
            settings=settings,
        )
